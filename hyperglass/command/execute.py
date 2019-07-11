"""
Accepts input from front end application, validates the input and
returns errors if input is invalid. Passes validated parameters to
construct.py, which is used to build & run the Netmiko connectoins or
hyperglass-frr API calls, returns the output back to the front end.
"""
# Standard Library Imports
import json
import time
import asyncio

# Third Party Imports
import http3
import http3.exceptions
from logzero import logger
from netmiko import ConnectHandler
from netmiko import NetMikoAuthenticationException
from netmiko import NetmikoAuthError
from netmiko import NetmikoTimeoutError
from netmiko import NetMikoTimeoutException
from netmiko import redispatch

# Project Imports
from hyperglass.command.construct import Construct
from hyperglass.command.validate import Validate
from hyperglass.configuration import credentials
from hyperglass.configuration import devices
from hyperglass.configuration import logzero_config  # noqa: F401
from hyperglass.configuration import params
from hyperglass.configuration import proxies
from hyperglass.constants import Supported
from hyperglass.constants import code


class Rest:
    """Executes connections to REST API devices"""

    def __init__(self, transport, device, query_type, target):
        self.transport = transport
        self.device = device
        self.query_type = query_type
        self.target = target
        self.cred = getattr(credentials, self.device.credential)
        self.query = getattr(Construct(self.device), self.query_type)(
            self.transport, self.target
        )

    async def frr(self):
        """Sends HTTP POST to router running the hyperglass-frr API"""
        logger.debug(f"FRR host params:\n{self.device}")
        logger.debug(f"Query parameters: {self.query}")

        try:
            headers = {
                "Content-Type": "application/json",
                "X-API-Key": self.cred.password.get_secret_value(),
            }
            frr_endpoint = (
                f"http://{self.device.address.exploded}:{self.device.port}/frr"
            )

            logger.debug(f"HTTP Headers: {headers}")
            logger.debug(f"FRR endpoint: {frr_endpoint}")

            http_client = http3.AsyncClient()
            frr_response = await http_client.post(
                frr_endpoint, headers=headers, json=self.query, timeout=7
            )
            response = frr_response.text
            status = frr_response.status_code

            logger.debug(f"FRR status code: {status}")
            logger.debug(f"FRR response text:\n{response}")
        except (
            http3.exceptions.ConnectTimeout,
            http3.exceptions.CookieConflict,
            http3.exceptions.DecodingError,
            http3.exceptions.InvalidURL,
            http3.exceptions.PoolTimeout,
            http3.exceptions.ProtocolError,
            http3.exceptions.ReadTimeout,
            http3.exceptions.RedirectBodyUnavailable,
            http3.exceptions.RedirectLoop,
            http3.exceptions.ResponseClosed,
            http3.exceptions.ResponseNotRead,
            http3.exceptions.StreamConsumed,
            http3.exceptions.Timeout,
            http3.exceptions.TooManyRedirects,
            http3.exceptions.WriteTimeout,
        ) as rest_error:
            logger.error(
                f"Error connecting to device {self.device.location}: {rest_error}"
            )
            response = params.messages.general
            status = code.invalid
        return response, status

    def bird(self):
        """Sends HTTP POST to router running the hyperglass-bird API"""
        logger.debug(f"BIRD host params:\n{self.device}")
        logger.debug(f"Query parameters: {self.query}")

        try:
            headers = {
                "Content-Type": "application/json",
                "X-API-Key": self.cred.password.get_secret_value(),
            }
            bird_endpoint = (
                f"http://{self.device.address.exploded}:{self.device.port}/bird"
            )

            logger.debug(f"HTTP Headers: {headers}")
            logger.debug(f"BIRD endpoint: {bird_endpoint}")

            http_client = http3.AsyncClient()
            bird_response = http_client.post(
                bird_endpoint, headers=headers, json=self.query, timeout=7
            )
            response = bird_response.text
            status = bird_response.status_code

            logger.debug(f"BIRD status code: {status}")
            logger.debug(f"BIRD response text:\n{response}")
        except (
            http3.exceptions.ConnectTimeout,
            http3.exceptions.CookieConflict,
            http3.exceptions.DecodingError,
            http3.exceptions.InvalidURL,
            http3.exceptions.PoolTimeout,
            http3.exceptions.ProtocolError,
            http3.exceptions.ReadTimeout,
            http3.exceptions.RedirectBodyUnavailable,
            http3.exceptions.RedirectLoop,
            http3.exceptions.ResponseClosed,
            http3.exceptions.ResponseNotRead,
            http3.exceptions.StreamConsumed,
            http3.exceptions.Timeout,
            http3.exceptions.TooManyRedirects,
            http3.exceptions.WriteTimeout,
        ) as rest_error:
            logger.error(f"Error connecting to device {self.device}: {rest_error}")
            response = params.messages.general
            status = code.invalid
        return response, status


class Netmiko:
    """Executes connections to Netmiko devices"""

    def __init__(self, transport, device, query_type, target):
        self.device = device
        self.target = target
        self.cred = getattr(credentials, self.device.credential)
        self.location, self.nos, self.command = getattr(Construct(device), query_type)(
            transport, target
        )
        self.nm_host = {
            "host": self.location,
            "device_type": self.nos,
            "username": self.cred.username,
            "password": self.cred.password.get_secret_value(),
            "global_delay_factor": 0.5,
        }

    def direct(self):
        """
        Connects to the router via netmiko library, return the command
        output.
        """
        logger.debug(f"Connecting to {self.device.location} via Netmiko library...")

        try:
            nm_connect_direct = ConnectHandler(**self.nm_host)
            response = nm_connect_direct.send_command(self.command)
            status = code.valid
            logger.debug(f"Response for direct command {self.command}:\n{response}")
        except (
            NetMikoAuthenticationException,
            NetMikoTimeoutException,
            NetmikoAuthError,
            NetmikoTimeoutError,
        ) as netmiko_exception:
            response = params.messages.general
            status = code.invalid
            logger.error(f"{netmiko_exception}, {status}")
        return response, status

    def proxied(self):
        """
        Connects to the proxy server via netmiko library, then logs
        into the router via SSH.
        """
        device_proxy = getattr(proxies, self.device.proxy)
        nm_proxy = {
            "host": device_proxy.address.exploded,
            "username": device_proxy.username,
            "password": device_proxy.password.get_secret_value(),
            "device_type": device_proxy.nos,
            "global_delay_factor": 0.5,
        }
        nm_connect_proxied = ConnectHandler(**nm_proxy)
        nm_ssh_command = device_proxy.ssh_command.format(**self.nm_host) + "\n"

        logger.debug(f"Netmiko proxy {self.device.proxy}")
        logger.debug(f"Proxy SSH command: {nm_ssh_command}")

        nm_connect_proxied.write_channel(nm_ssh_command)
        time.sleep(1)
        proxy_output = nm_connect_proxied.read_channel()

        logger.debug(f"Proxy output:\n{proxy_output}")

        try:
            # Accept SSH key warnings
            if "Are you sure you want to continue connecting" in proxy_output:
                logger.debug("Received OpenSSH key warning")
                nm_connect_proxied.write_channel("yes" + "\n")
                nm_connect_proxied.write_channel(self.nm_host["password"] + "\n")
            # Send password on prompt
            elif "assword" in proxy_output:
                logger.debug("Received password prompt")
                nm_connect_proxied.write_channel(self.nm_host["password"] + "\n")
                proxy_output += nm_connect_proxied.read_channel()
            # Reclassify netmiko connection as configured device type
            logger.debug(
                f'Redispatching netmiko with device class {self.nm_host["device_type"]}'
            )
            redispatch(nm_connect_proxied, self.nm_host["device_type"])
            response = nm_connect_proxied.send_command(self.command)
            status = code.valid

            logger.debug(f"Netmiko proxied response:\n{response}")
        except (
            NetMikoAuthenticationException,
            NetMikoTimeoutException,
            NetmikoAuthError,
            NetmikoTimeoutError,
        ) as netmiko_exception:
            response = params.messages.general
            status = code.invalid

            logger.error(f"{netmiko_exception}, {status},Proxy: {self.device.proxy}")
        return response, status


class Execute:
    """
    Ingests user input, runs blacklist check, runs prefix length check
    (if enabled), pulls all configuraiton variables for the input
    router.
    """

    def __init__(self, lg_data):
        self.input_data = lg_data
        self.input_location = self.input_data["location"]
        self.input_type = self.input_data["type"]
        self.input_target = self.input_data["target"]

    def parse(self, output, nos):
        """
        Splits BGP output by AFI, returns only IPv4 & IPv6 output for
        protocol-agnostic commands (Community & AS_PATH Lookups).
        """
        logger.debug("Parsing output...")

        parsed = output
        if self.input_type in ("bgp_community", "bgp_aspath"):
            if nos in ("cisco_ios",):
                logger.debug(f"Parsing output for device type {nos}")

                delimiter = "For address family: "
                parsed_ipv4 = output.split(delimiter)[1]
                parsed_ipv6 = output.split(delimiter)[2]
                parsed = delimiter + parsed_ipv4 + delimiter + parsed_ipv6
            elif nos in ("cisco_xr",):
                logger.debug(f"Parsing output for device type {nos}")

                delimiter = "Address Family: "
                parsed_ipv4 = output.split(delimiter)[1]
                parsed_ipv6 = output.split(delimiter)[2]
                parsed = delimiter + parsed_ipv4 + delimiter + parsed_ipv6
        return parsed

    async def response(self):
        """
        Initializes Execute.filter(), if input fails to pass filter,
        returns errors to front end. Otherwise, executes queries.
        """
        device_config = getattr(devices, self.input_location)

        logger.debug(f"Received query for {self.input_data}")
        logger.debug(f"Matched device config:\n{device_config}")

        # Run query parameters through validity checks
        validity, msg, status = getattr(Validate(device_config), self.input_type)(
            self.input_target
        )
        if not validity:
            logger.debug("Invalid query")
            return (msg, status)
        connection = None
        output = params.messages.general

        logger.debug(f"Validity: {validity}, Message: {msg}, Status: {status}")

        if Supported.is_rest(device_config.nos):
            connection = Rest("rest", device_config, self.input_type, self.input_target)
            raw_output, status = await getattr(connection, device_config.nos)()
            output = self.parse(raw_output, device_config.nos)
        elif Supported.is_scrape(device_config.nos):
            logger.debug("Initializing Netmiko...")

            connection = Netmiko(
                "scrape", device_config, self.input_type, self.input_target
            )
            if device_config.proxy:
                raw_output, status = connection.proxied()
            elif not device_config.proxy:
                raw_output, status = connection.direct()
            output = self.parse(raw_output, device_config.nos)

            logger.debug(
                f"Parsed output for device type {device_config.nos}:\n{output}"
            )
        return (output, status)
