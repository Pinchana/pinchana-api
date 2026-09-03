from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "dlp-prod-preflight.py"
SPEC = importlib.util.spec_from_file_location("dlp_prod_preflight", SCRIPT)
assert SPEC and SPEC.loader
dlp_prod_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dlp_prod_preflight)


class VpnCredentialsTests(unittest.TestCase):
    def test_accepts_wireguard_credentials(self) -> None:
        dlp_prod_preflight.validate_vpn_credentials(
            {
                "VPN_TYPE": "wireguard",
                "WIREGUARD_PRIVATE_KEY": "a" * 44,
                "SERVER_COUNTRIES": "Ukraine,Poland,Moldova",
            }
        )

    def test_accepts_openvpn_service_credentials(self) -> None:
        dlp_prod_preflight.validate_vpn_credentials(
            {
                "VPN_TYPE": "openvpn",
                "OPENVPN_USER": "service-user",
                "OPENVPN_PASSWORD": "service-password",
                "OPENVPN_PROTOCOL": "tcp",
                "SERVER_COUNTRIES": "United States,Netherlands",
            }
        )

    def test_rejects_missing_openvpn_credentials(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "OPENVPN_USER"):
            dlp_prod_preflight.validate_vpn_credentials({"VPN_TYPE": "openvpn"})

    def test_rejects_country_separator_whitespace(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "SERVER_COUNTRIES"):
            dlp_prod_preflight.validate_vpn_credentials(
                {
                    "VPN_TYPE": "wireguard",
                    "WIREGUARD_PRIVATE_KEY": "a" * 44,
                    "SERVER_COUNTRIES": "Ukraine, Poland",
                }
            )


if __name__ == "__main__":
    unittest.main()
