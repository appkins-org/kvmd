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

import functools

from typing import Callable, Coroutine, Any

from aiohttp.web import Request
from aiohttp.web import Response

from ....htserver import HttpError
from ....htserver import exposed_http
from ....htserver import make_json_response

from ....plugins.atx import BaseAtx

from ....validators import ValidatorError
from ....validators import check_string_in_list
from ....validators.ugpio import valid_ugpio_channel

from ....logging import get_logger

from ..info import InfoManager

from ..ugpio import UserGpio

from .... import aiotools


# =====
class RedfishApi:
    # https://github.com/DMTF/Redfishtool
    # https://github.com/DMTF/Redfish-Mockup-Server
    # https://redfish.dmtf.org/redfish/v1
    # https://www.dmtf.org/documents/redfish-spmf/redfish-mockup-bundle-20191
    # https://www.dmtf.org/sites/default/files/Redfish_School-Sessions.pdf
    # https://www.ibm.com/support/knowledgecenter/POWER9/p9ej4/p9ej4_kickoff.htm
    #
    # Quick examples:
    #    redfishtool -S Never -u admin -p admin -r localhost:8080 Systems
    #    redfishtool -S Never -u admin -p admin -r localhost:8080 Systems reset ForceOff

    def __init__(
        self,
        info_manager: InfoManager,
        atx: BaseAtx,
        user_gpio: UserGpio
    ) -> None:
        self.__info_manager = info_manager
        self.__atx = atx
        self.__user_gpio = user_gpio

        self.__actions: dict[
            str,
            dict[str, Callable[[Any], bool], None]
            ] = {
            "pikvm": {
                "ComputerSystem.Reset": {
                    "On": self.__atx.power_on,
                    "ForceOff": self.__atx.power_off_hard,
                    "GracefulShutdown": self.__atx.power_off,
                    "ForceRestart": self.__atx.power_reset_hard,
                    "ForceOn": self.__atx.power_on,
                    "PushPowerButton": self.__atx.click_power,
                }
            }
        }

        self.__power_state: dict[str, Callable[[], bool]] = {
            "pikvm": functools.partial(
                self.get_state,
                self.__atx.get_state,
                lambda st: st.get("leds", {})["power"]
            )
        }

        def split_channel(channel: str) -> tuple[str, str]:
            pts = channel.split("_")
            sys_id = pts[0]
            if sys_id not in self.__actions:
                self.__actions[sys_id] = {}
            return (sys_id, "_".join(pts[1:]))

        async def cycle(c: str, delay: float, wait: bool) -> None:
            get_logger().info(
                "CYCLE CHANNEL: %s",
                c
            )
            # valid_ugpio_channel(c)
            await self.__user_gpio.pulse(c, delay, wait)

        async def sw(c: str, state: bool, wait: bool) -> None:
            get_logger().info(
                "SWITCH CHANNEL: %s",
                c
            )
            valid_ugpio_channel(c)
            await self.__user_gpio.switch(c, state, wait)

        def select_state(channel: str, state: dict[str, dict[str, bool]]) -> bool:
            return state["outputs"][channel]["state"]

        async def inner_init() -> None:
            state = await self.__user_gpio.get_state()

            for channel in state["outputs"].keys():
                (sys_id, action_name) = split_channel(channel)

                if "ComputerSystem.Reset" not in self.__actions[sys_id]:
                    self.__actions[sys_id]["ComputerSystem.Reset"] = {}

                if action_name == "cycle":
                    self.__actions[sys_id]["ComputerSystem.Reset"].update({
                        "ForceRestart": functools.partial(cycle, channel, 0.5),
                    })

                if action_name == "power":
                    ch = channel
                    get_logger().info(
                        "ADDING: %s",
                        ch
                    )

                    self.__power_state[sys_id] = functools.partial(
                        self.get_state,
                        self.__user_gpio.get_state,
                        functools.partial(select_state, channel)
                    )

                    on = functools.partial(sw, channel, True)
                    off = functools.partial(sw, channel, False)

                    self.__actions[sys_id][
                        "ComputerSystem.Reset"
                    ].update({
                        "On": on,
                        "ForceOn": on,
                        "ForceOff": off,
                        "GracefulShutdown": off,
                        "PushPowerButton": off,
                    })
                else:
                    get_logger().info(
                        "NOT ADDING: %s",
                        channel
                    )

        aiotools.run_sync(inner_init())

    async def get_state(self, inner_get_state: Callable[[], Coroutine[Any, Any, dict]], sel: Callable[[dict], bool]):
        st = await inner_get_state()
        state: bool = sel(st)
        return "On" if state else "Off"

    @exposed_http("GET", "/redfish/v1", auth_required=False)
    async def __root_handler(self, _: Request) -> Response: # pylint: disable=unused-private-member
        return make_json_response({
            "@odata.id": "/redfish/v1",
            "@odata.type": "#ServiceRoot.v1_6_0.ServiceRoot",
            "Id": "RootService",
            "Name": "Root Service",
            "RedfishVersion": "1.6.0",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
        }, wrap_result=False)

    @exposed_http("GET", "/redfish/v1/Systems")
    async def __systems_handler(self, _: Request) -> Response: # pylint: disable=unused-private-member
        return make_json_response({
            "@odata.id": "/redfish/v1/Systems",
            "@odata.type": "#ComputerSystemCollection.ComputerSystemCollection",
            "Members": [
                {
                    "@odata.id": f"/redfish/v1/Systems/{a}"
                } for a in self.__actions
            ],
            "Members@odata.count": 1,
            "Name": "Computer System Collection",
        }, wrap_result=False)

    @exposed_http("GET", "/redfish/v1/Systems/{id}")
    async def __server_handler(self, request: Request) -> Response: # pylint: disable=unused-private-member
        meta_state = await self.__info_manager.get_submanager("meta").get_state()
        system_id = request.match_info['id']
        try:
            host = meta_state.get("server", {})["host"]
        except Exception: # pylint: disable=broad-exception-caught
            host = ""
        actions = {}
        for k, a in self.__actions[system_id].items():
            sk = k.split(".")[1]
            actions[f"#{k}"] = {
                    f"{sk}Type@Redfish.AllowableValues": list(a.keys()),
                    "target": f"/redfish/v1/Systems/{system_id}/Actions/{k}"
                }
        pwr_state = await self.__power_state.get(system_id)()
        return make_json_response({
            "@odata.id": f"/redfish/v1/Systems/{system_id}",
            "@odata.type": "#ComputerSystem.v1_10_0.ComputerSystem",
            "Actions": actions,
            "Id": system_id,
            "HostName": host,
            "PowerState": pwr_state,
        }, wrap_result=False)

    @exposed_http("POST", "/redfish/v1/Systems/{id}/Actions/{action}")
    async def __action_handler(self, request: Request) -> Response: # pylint: disable=unused-private-member
        system_id = request.match_info['id']
        action_name = request.match_info['action']
        action_sets = self.__actions[system_id]
        try:
            action_set = check_string_in_list(
                arg=action_name,
                name="Redfish Action",
                variants=set(action_sets.keys()),
                lower=False,
            )
            actions = action_sets[action_set]
            variant = None
            match action_set:
                case "ComputerSystem.Reset":
                    variant = (await request.json())["ResetType"]
                case _:
                    variant = None
            action = check_string_in_list(
                arg=variant,
                name="Redfish ResetType",
                variants=set(actions.keys()),
                lower=False,
            )
        except ValidatorError:
            raise
        except Exception:
            raise HttpError("Missing Redfish Action", 400) # pylint: disable=W0707
        await actions[action](False)
        return Response(body=None, status=204)
