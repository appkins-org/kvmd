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
        state_poll: float,
        timeout: float,
    ) -> None:

        super().__init__(instance_name, notifier)

        self.__url = url
        self.__verify = verify
        self.__user = user
        self.__passwd = passwd
        self.__mac = mac
        self.__state_poll = state_poll
        self.__timeout = timeout

        self.__initial: dict[str, (bool | None)] = {}

        self.__state: dict[str, (bool | None)] = {}
        
        self.__port_table: dict[str, dict[str, any]] = {}
        
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
        for (pin, state) in self.__initial.items():
            if state is None:
                state = False
            self.__state[pin] = state # { "poe_enable": state }
        
        return
        # async def inner_prepare() -> None:
        #     await asyncio.gather(*[
        #         self.write(pin, state)
        #         for (pin, state) in self.__initial.items()
        #         if state is not None
        #     ], return_exceptions=True)
        # aiotools.run_sync(inner_prepare())

    # async def login(self) -> None:
    #     session = await self.__ensure_http_session()
    #     get_logger().info(
    #         "Logging into UNIFI"
    #     )
    #     try:
    #         async with session.post(
    #             url=f"{self.__url}/api/auth/login",
    #             json={
    #                 "username": self.__user,
    #                 "password": self.__passwd
    #             },
    #             verify_ssl=self.__verify,
    #         ) as response:
    #             htclient.raise_not_200(response)
    #             if "X-CSRF-TOKEN" in [h.upper() for h in response.headers]:
    #                 self.__csrf_token = response.headers["X-CSRF-TOKEN"]
    #             if response.cookies:
    #                 session.cookie_jar.update_cookies(
    #                     response.cookies
    #                 )
    #     except Exception as err:
    #         get_logger().error(
    #             "Failed UNIFI login request: %s",
    #             tools.efmt(err)
    #         )

    async def run(self) -> None:
        prev_state: (dict | None) = None
        while True:
            session = await self.__ensure_http_session()
            try:
                # if self.__csrf_token is None:
                #     await self.login()
                async with session.get(
                    url=f"{self.__api_url}/stat/device/{self.__mac}",
                    headers=self.__get_headers(),
                    verify_ssl=self.__verify
                ) as response:
                    # self.__set_headers(response.headers)
                    htclient.raise_not_200(response)
                    
                    for header in response.headers:
                        if header.upper() == "X-CSRF-TOKEN":
                            self.__csrf_token = response.headers[header]
                    
                    status = (await response.json())["data"][0]
                    if self.__id is None or self.__id != status["_id"]:
                        self.__id = status["_id"]
                    
                    self.__port_table = dict(map(lambda port: (str(port["port_idx"]), port), list(filter(lambda p: "poe_enable" in p.keys(), status["port_table"]))))
                    
                    # self.__state = map(lambda pin: self.__port_table[pin-1]["poe_enabled"], self.__state)
                    for pin in self.__state:
                        if pin is not None:
                            self.__state[pin] = self.__port_table[pin]["poe_enable"]
                            # port = status["port_table"][pin-1]
                            # if port["port_idx"] == pin:
                            #     self.__state[pin] = port
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
            self.__csrf_token = None

    async def read(self, pin: str) -> bool:
        try:
            return await self.__inner_read(pin)
        except Exception as err:
            raise err
            # raise GpioDriverOfflineError(self)

    async def write(self, pin: str, state: bool) -> None:
        try:
            await self.__inner_write(pin, state)
        except Exception as err:
            get_logger().error(
                "Failed UNIFI PUT request | pin : %s | Error: %s",
                pin,
                tools.efmt(err)
            )
            # raise err
            # raise GpioDriverOfflineError(self)
        
        # if self.__should_cycle(pin) is True:
        #     await asyncio.sleep(1)
        #     return
        
        self.__update_notifier.notify()

    # =====
    
    def __should_cycle(self, pin: str) -> bool:
        cycle = self.__initial[pin]
        if cycle is None:
            cycle = False
        return cycle

    async def __inner_read(self, pin: str) -> bool:
        if pin in self.__state and self.__state[pin] is not None:
            return self.__state[pin]
            # return self.__state[pin]["poe_enable"]
        get_logger().error("Failed to find pin: %s", pin)
        self.__state[pin] = False
        # self.__state[pin] = { "poe_enable": False }
        await self.__inner_run()
        return False

    async def __inner_run(self) -> None:
        session = await self.__ensure_http_session()
        try:
            # if self.__csrf_token is None:
            #     await self.login()
            async with session.get(
                url=f"{self.__api_url}/stat/device/{self.__mac}",
                headers=self.__get_headers(),
                verify_ssl=self.__verify
            ) as response:
                # if response.status == 400:
                #     self.__csrf_token = None
                
                # self.__set_headers(response.headers)
                htclient.raise_not_200(response)
                
                for header in response.headers:
                    if header.upper() == "X-CSRF-TOKEN":
                        self.__csrf_token = response.headers[header]
                
                status = (await response.json())["data"][0]
                if self.__id is None or self.__id != status["_id"]:
                    self.__id = status["_id"]
                
                self.__port_table = dict(map(lambda port: (str(port["port_idx"]), port), list(filter(lambda p: "poe_enable" in p.keys(), status["port_table"]))))
                
                # self.__state = map(lambda pin: self.__port_table[pin-1]["poe_enabled"], self.__state)
                for pin in self.__state:
                    if pin is not None:
                        self.__state[pin] = self.__port_table[pin]["poe_enable"]
        except Exception as err:
            get_logger().error("Failed UNIFI bulk GET request: %s", tools.efmt(err))
        finally:
            get_logger().info("UNIFI status: %s", self.__state)

    async def __inner_write(self, pin: str, state: bool) -> None:
        # if self.__should_cycle(pin) is True:
        #     await self.__cycle_device(pin, state)
        # else:
        await self.__set_device(pin, state)

    async def __cycle_device(self, pin: str, state: bool) -> None:
        if state is False:
            return
        session = await self.__ensure_http_session()
        get_logger().info("Cycling device %s: port: %s", self.__mac, pin)
        async with session.post(
            url=f"{self.__api_url}/cmd/devmgr",
            json={
                "cmd": "power-cycle",
                "mac": self.__mac,
                "port_idx": pin,
            },
            headers=self.__get_headers(),
            verify_ssl=self.__verify,
        ) as response:
            self.__set_headers(response.headers)
            htclient.raise_not_200(response)
                
    async def __set_device(self, pin: str, state: bool) -> None:
        session = await self.__ensure_http_session()
        
        # if self.__state[pin] == state:
        #     return
        
        port = self.__port_table[pin]
        
        # if self.__state[pin]["poe_enable"] == state:
        #     return

        # self.__state[pin]["poe_enable"] = state
        # self.__state[pin]["poe_mode"] = "auto" if state else "off"

        # port_overrides = [port] # [self.__state[pin]]
        
        data={
            "port_overrides": [{
                "native_networkconf_id": port["native_networkconf_id"],
                "port_idx": port["port_idx"],
                "poe_enable": state,
                "poe_mode": "auto" if state else "off",
                "name": port["name"],
                "op_mode": port["op_mode"],
            }]
        }

        get_logger().info("Posting content %s: %s", pin, data)
        
        async with session.put(
            url=f"{self.__api_url}/rest/device/{self.__id}",
            json=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json;charset=UTF-8",
                "X-CSRF-TOKEN": self.__csrf_token,
                "User-Agent": htclient.make_user_agent("KVMD"),
            },
            verify_ssl=self.__verify,
        ) as response:
            # self.__set_headers(response.headers)
            # if response.status == 400:
            #     self.__csrf_token = None
            htclient.raise_not_200(response)
            
            for header in response.headers:
                if header.upper() == "X-CSRF-TOKEN":
                    self.__csrf_token = response.headers[header]
            
            if response.cookies:
                self.__http_session.cookie_jar.update_cookies(
                    response.cookies
                )

            self.__state[pin] = state
            self.__port_table[pin]["poe_enable"] = state

    # async def __inner_login(self) -> None:
    #     session = await self.__ensure_http_session()
    #     async with session.post(
    #         url=f"{self.__url}/api/auth/login",
    #         json={
    #             "username": self.__user,
    #             "password": self.__passwd
    #         },
    #         verify_ssl=self.__verify,
    #     ) as response:
    #         htclient.raise_not_200(response)
    #         if "X-CSRF-TOKEN" in [h.upper() for h in response.headers]:
    #             self.__csrf_token = response.headers["X-CSRF-TOKEN"]
    #         if response.cookies:
    #             session.cookie_jar.update_cookies(
    #                 response.cookies
    #             )

    def __get_headers(self, extra: (dict[str, str] | None) = None) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "X-CSRF-TOKEN": self.__csrf_token,
        }
        return headers.update(extra) if (extra is not None) else headers

    def __set_headers(self, response_headers: dict[str, str]) -> None:
        if "X-CSRF-TOKEN" in [h.upper() for h in response_headers]:
            self.__csrf_token = response_headers["X-CSRF-TOKEN"]
            
    async def login(self) -> None:
        try:
            response = await self.__http_session.post(
                url=f"{self.__url}/api/auth/login",
                json={
                    "username": self.__user,
                    "password": self.__passwd
                },
                headers={
                    "Accept": "application/json",
                    "User-Agent": htclient.make_user_agent("KVMD"),
                    "Content-Type": "application/json;charset=UTF-8",
                },
                verify_ssl=self.__verify,
            )
            
            htclient.raise_not_200(response)
            
            for header in response.headers:
                if header.upper() == "X-CSRF-TOKEN":
                    self.__csrf_token = response.headers[header]

            if response.cookies:
                self.__http_session.cookie_jar.update_cookies(
                    response.cookies
                )
        except Exception as err:
            get_logger().error(
                "Failed UNIFI login request: %s",
                tools.efmt(err)
            )

    async def __ensure_http_session(self) -> aiohttp.ClientSession:
        if self.__http_session is None:
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
            get_logger(0).info("Opened %s on %s", self, self.__http_session)

        if self.__csrf_token is None:
            get_logger().info(
                "Logging into UNIFI"
            )
            await self.login()
        return self.__http_session

    def __str__(self) -> str:
        return f"UNIFI({self._instance_name})"

    __repr__ = __str__
