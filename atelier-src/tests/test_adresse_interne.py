"""`is_internal_request` : le loopback et les plages privées, pas tout `172.*`.

`172.*` entier laissait passer des adresses publiques (`172.0.0.1`,
`172.217.x.x`…) : seul `172.16.0.0/12` est privé (RFC 1918).
"""

from __future__ import annotations

import pytest

from mcp_gateway.atelier.vscode_proxy import est_adresse_interne


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.0.0.2", "::1", "::ffff:127.0.0.1", "10.233.115.38", "192.168.1.10",
     "172.16.0.5", "172.31.255.254", "::ffff:10.0.0.1"],
)
def test_les_adresses_du_cluster_sont_internes(host: str) -> None:
    assert est_adresse_interne(host)


@pytest.mark.parametrize(
    "host",
    ["172.0.0.1", "172.15.255.255", "172.32.0.1", "172.217.19.46", "8.8.8.8", "169.254.169.254",
     "2001:db8::1", "::ffff:8.8.8.8", "localhost", "", "testclient", "10.0.0.1.evil.example"],
)
def test_le_reste_n_est_pas_interne(host: str) -> None:
    assert not est_adresse_interne(host)
