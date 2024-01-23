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

from typing import AsyncGenerator
from typing import Callable
from typing import Any

from ...logging import get_logger

from ...errors import IsBusyError

from ... import tools
from ... import aiotools

from ...plugins.ugpio import GpioError
from ...plugins.ugpio import GpioOperationError
from ...plugins.ugpio import GpioDriverOfflineError
from ...plugins.ugpio import UserGpioModes
from ...plugins.ugpio import BaseUserGpioDriver
from ...plugins.ugpio import get_ugpio_driver_class

from ...yamlconf import Section

