# ========================================================================== #
#                                                                            #
#    KVMD - The main PiKVM daemon.                                           #
#                                                                            #
#    Copyright (C) 2018-2023  Maxim Devaev <mdevaev@gmail.com>               #
#                                                                            #
#    This program is free software: you can redistribute it and/or modify    #
#    it under the terms of the GNU General Public License as published by    #
#    the Free Software Foundation, either version 3 of the License, or       #
#    (at your option) any later version.                                     #
#                                                                            #
#    This program is distributed in the hope that it will be useful,         #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#    GNU General Public License for more details.                            #
#                                                                            #
#    You should have received a copy of the GNU General Public License       #
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.  #
#                                                                            #
# ========================================================================== #


import asyncio
import contextlib
import functools

from typing import Callable
from typing import Any

import aiohttp

from ...logging import get_logger

from ... import tools
from ... import aiotools
from ... import htclient

from ...yamlconf import Option

from ...validators.basic import valid_stripped_string_not_empty
from ...validators.basic import valid_bool
from ...validators.basic import valid_number
from ...validators.basic import valid_float_f01

from . import BaseUserGpioDriver
from . import GpioDriverOfflineError


# =====
class Plugin(BaseUserGpioDriver):  # pylint: disable=too-many-instance-attributes
    def __init__(
        self,
        instance_name: str,
        notifier: aiotools.AioNotifier,

        url: str,
        verify: bool,
        user: str,
        passwd: str,
        mac: str,
        cycle: bool,
        state_poll: float,
        timeout: float,
    ) -> None:

        super().__init__(instance_name, notifier)

        self.__url = url
        self.__verify = verify
        self.__user = user
        self.__passwd = passwd
        self.__mac = mac
        self.__cycle = cycle
        self.__state_poll = state_poll
        self.__timeout = timeout

        self.__initial: dict[str, (bool | None)] = {}

        self.__state: dict[str, (bool | None)] = {}
        self.__update_notifier = aiotools.AioNotifier()

        self.__http_session: (aiohttp.ClientSession | None) = None

        self.__csrf_token: (str | None) = None
        self.__id: (str | None) = None
        self.__api_url: str = f"{self.__url}/proxy/network/api/s/default"

    @classmethod
    def get_plugin_options(cls) -> dict[str, Option]:
        return {
            "url":        Option("",   type=valid_stripped_string_not_empty),
            "verify":     Option(True, type=valid_bool),
            "user":       Option(""),
            "passwd":     Option(""),
            "mac":        Option("",   type=valid_stripped_string_not_empty),
            "cycle":      Option(False, type=valid_bool), # Cycle power on boot mode
            "state_poll": Option(5.0,  type=valid_float_f01),
            "timeout":    Option(5.0,  type=valid_float_f01),
        }

    @classmethod
    def get_pin_validator(cls) -> Callable[[Any], Any]:
        return functools.partial(valid_number, min=0, max=47, name="UNIFI port")

    def register_input(self, pin: str, debounce: float) -> None:
        _ = debounce
        self.__state[pin] = None

    def register_output(self, pin: str, initial: (bool | None)) -> None:
        self.__initial[pin] = initial
        self.__state[pin] = None

    def prepare(self) -> None:
        async def inner_prepare() -> None:
            await asyncio.gather(*[
                self.write(pin, state)
                for (pin, state) in self.__initial.items()
                if state is not None
            ], return_exceptions=True)
        aiotools.run_sync(inner_prepare())

    async def login(self) -> None:
        try:
            self.__inner_login()
        except Exception as err:
            get_logger().error(
                "Failed UNIFI login request: %s",
                tools.efmt(err)
            )

    async def run(self) -> None:
        prev_state: (dict | None) = None
        while True:
            try:
                self.__inner_run()
            except Exception as err:
                get_logger().error("Failed UNIFI bulk GET request: %s", tools.efmt(err))
                self.__state = dict.fromkeys(self.__state, None)
            if self.__state != prev_state:
                self._notifier.notify()
                prev_state = self.__state
            # for port in self.__state.values():
            #     if port["poe_enable"] != port["poe_good"]:
            #         await asyncio.sleep(1)
            #         self._notifier.notify()
            await self.__update_notifier.wait(self.__state_poll)

    async def cleanup(self) -> None:
        if self.__http_session:
            await self.__http_session.close()
            self.__http_session = None

    async def read(self, pin: str) -> bool:
        try:
            return self.__inner_read(int(pin))
        except Exception:
            raise GpioDriverOfflineError(self)

    async def write(self, pin: str, state: bool) -> None:
        try:
            self.__inner_write(int(pin), state)
        except Exception as err:
            get_logger().error(
                "Failed UNIFI PUT request | pin : %s | Error: %s",
                pin,
                tools.efmt(err)
            )
            raise GpioDriverOfflineError(self)
        self.__update_notifier.notify()

    # =====

    def __inner_read(self, pin: int) -> bool:
        if self.__state[pin] is None:
            raise GpioDriverOfflineError(self)
        return self.__state[pin]["poe_enable"]

    async def __inner_run(self) -> None:
        with self.__ensure_http_session("running") as session:
            if self.__csrf_token is None:
                await self.login()

            async with session.get(
                url=f"{self.__api_url}/stat/device/{self.__mac}",
                headers={
                    "Accept": "application/json",
                    "X-CSRF-TOKEN": self.__csrf_token,
                },
                verify_ssl=self.__verify,
            ) as response:
                if "X-CSRF-TOKEN" in [h.upper() for h in response.headers]:
                    self.__csrf_token = response.headers["X-CSRF-TOKEN"]
                htclient.raise_not_200(response)
                status = (await response.json())["data"][0]
                if self.__id is None or self.__id != status["_id"]:
                    self.__id = status["_id"]
                for pin in self.__state:
                    self.__state[pin] = status["port_table"][int(pin)]

    async def __inner_write(self, pin: int, state: bool) -> None:
        with self.__ensure_http_session("writing") as session:
            if self.__state[pin]["poe_enable"] == state:
                return

            self.__state[pin]["poe_enable"] = state
            self.__state[pin]["poe_mode"] = "auto" if state else "off"

            port_overrides = [self.__state[pin]]

            get_logger().info("Posting content %s: %s", pin, port_overrides)
            async with session.put(
                url=f"{self.__api_url}/rest/device/{self.__id}",
                json={"port_overrides": port_overrides},
                headers=self.__get_headers(),
                verify_ssl=self.__verify,
            ) as response:
                self.__set_headers(response.headers)
                htclient.raise_not_200(response)

    async def __inner_login(self) -> None:
        with self.__ensure_http_session("login") as session:
            async with session.post(
                url=f"{self.__url}/api/auth/login",
                json={
                    "username": self.__user,
                    "password": self.__passwd
                },
                verify_ssl=self.__verify,
            ) as response:
                htclient.raise_not_200(response)
                if "X-CSRF-TOKEN" in [h.upper() for h in response.headers]:
                    self.__csrf_token = response.headers["X-CSRF-TOKEN"]
                if response.cookies:
                    session.cookie_jar.update_cookies(
                        response.cookies
                    )

    def __get_headers(self, extra: dict[str, str] = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-CSRF-TOKEN": self.__csrf_token,
        }
        return headers.copy(extra) if extra else headers

    def __set_headers(self, response_headers: dict[str, str]) -> None:
        if "X-CSRF-TOKEN" in [h.upper() for h in response_headers]:
            self.__csrf_token = response_headers["X-CSRF-TOKEN"]

    @contextlib.contextmanager
    def __ensure_http_session(self, context: str) -> aiohttp.ClientSession:
        if not self.__http_session:
            kwargs: dict = {
                "headers": {
                    "Accept": "application/json",
                    "User-Agent": htclient.make_user_agent("KVMD"),
                },
                "timeout": aiohttp.ClientTimeout(total=self.__timeout),
            }

            if not self.__verify:
                kwargs["connector"] = aiohttp.TCPConnector(ssl=False)

            self.__http_session = aiohttp.ClientSession(**kwargs)
            get_logger(0).info("Opened %s on %s while %s", self, self.__http_session, context)
        try:
            yield self.__http_session
        except Exception as err:
            get_logger(0).error("Error occured on %s on %s while %s: %s",
                                self, self.__http_session, context, tools.efmt(err))
            self.cleanup()
            raise

    def __str__(self) -> str:
        return f"UNIFI({self._instance_name})"

    __repr__ = __str__
