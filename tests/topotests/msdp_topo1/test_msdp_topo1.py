#!/usr/bin/env python
# SPDX-License-Identifier: ISC

#
# test_msdp_topo1.py
# Part of NetDEF Topology Tests
#
# Copyright (c) 2021 by
# Network Device Education Foundation, Inc. ("NetDEF")
#

"""
test_msdp_topo1.py: Test the FRR PIM MSDP peer.
"""

import os
import sys
import json
from functools import partial
import re
import pytest

# Save the Current Working Directory to find configuration files.
CWD = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(CWD, "../"))

# pylint: disable=C0413
# Import topogen and topotest helpers
from lib import topotest

# Required to instantiate the topology builder class.
from lib.topogen import Topogen, TopoRouter, get_topogen
from lib.topolog import logger

from lib.pim import McastTesterHelper

pytestmark = [pytest.mark.bgpd, pytest.mark.pimd]

app_helper = McastTesterHelper()


def build_topo(tgen):
    "Build function"

    # Create 4 routers
    for routern in range(1, 5):
        tgen.add_router("r{}".format(routern))

    switch = tgen.add_switch("s1")
    switch.add_link(tgen.gears["r1"])
    switch.add_link(tgen.gears["r2"])

    switch = tgen.add_switch("s2")
    switch.add_link(tgen.gears["r1"])
    switch.add_link(tgen.gears["r3"])

    switch = tgen.add_switch("s3")
    switch.add_link(tgen.gears["r2"])
    switch.add_link(tgen.gears["r4"])

    switch = tgen.add_switch("s4")
    # switch.add_link(tgen.gears["r3"])
    switch.add_link(tgen.gears["r4"])

    switch = tgen.add_switch("s5")
    switch.add_link(tgen.gears["r4"])

    # Create a host connected and direct at r4:
    tgen.add_host("h1", "192.168.4.100/24", "via 192.168.4.1")
    tgen.add_host("h3", "192.168.4.120/24", "via 192.168.4.1")
    switch.add_link(tgen.gears["h1"])
    switch.add_link(tgen.gears["h3"])

    # Create a host connected and direct at r1:
    switch = tgen.add_switch("s6")
    tgen.add_host("h2", "192.168.10.100/24", "via 192.168.10.1")
    switch.add_link(tgen.gears["r1"])
    switch.add_link(tgen.gears["h2"])


def setup_module(mod):
    "Sets up the pytest environment"
    tgen = Topogen(build_topo, mod.__name__)
    tgen.start_topology()

    router_list = tgen.routers()
    for rname, router in router_list.items():
        daemon_file = "{}/{}/zebra.conf".format(CWD, rname)
        if os.path.isfile(daemon_file):
            router.load_config(TopoRouter.RD_ZEBRA, daemon_file)

        daemon_file = "{}/{}/bgpd.conf".format(CWD, rname)
        if os.path.isfile(daemon_file):
            router.load_config(TopoRouter.RD_BGP, daemon_file)

        daemon_file = "{}/{}/pimd.conf".format(CWD, rname)
        if os.path.isfile(daemon_file):
            router.load_config(TopoRouter.RD_PIM, daemon_file)

    # Initialize all routers.
    tgen.start_router()

    app_helper.init(tgen)


def teardown_module():
    "Teardown the pytest environment"
    tgen = get_topogen()
    app_helper.cleanup()
    tgen.stop_topology()


def test_bgp_convergence():
    "Wait for BGP protocol convergence"
    tgen = get_topogen()
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    logger.info("waiting for protocols to converge")

    def expect_loopback_route(router, iptype, route, proto):
        "Wait until route is present on RIB for protocol."
        logger.info("waiting route {} in {}".format(route, router))
        test_func = partial(
            topotest.router_json_cmp,
            tgen.gears[router],
            "show {} route json".format(iptype),
            {route: [{"protocol": proto}]},
        )
        _, result = topotest.run_and_expect(test_func, None, count=130, wait=1)
        assertmsg = '"{}" convergence failure'.format(router)
        assert result is None, assertmsg

    # Wait for R1
    expect_loopback_route("r1", "ip", "10.254.254.2/32", "bgp")
    expect_loopback_route("r1", "ip", "10.254.254.3/32", "bgp")
    expect_loopback_route("r1", "ip", "10.254.254.4/32", "bgp")

    # Wait for R2
    expect_loopback_route("r2", "ip", "10.254.254.1/32", "bgp")
    expect_loopback_route("r2", "ip", "10.254.254.3/32", "bgp")
    expect_loopback_route("r2", "ip", "10.254.254.4/32", "bgp")

    # Wait for R3
    expect_loopback_route("r3", "ip", "10.254.254.1/32", "bgp")
    expect_loopback_route("r3", "ip", "10.254.254.2/32", "bgp")
    expect_loopback_route("r3", "ip", "10.254.254.4/32", "bgp")

    # Wait for R4
    expect_loopback_route("r4", "ip", "10.254.254.1/32", "bgp")
    expect_loopback_route("r4", "ip", "10.254.254.2/32", "bgp")
    expect_loopback_route("r4", "ip", "10.254.254.3/32", "bgp")


def _test_mroute_install():
    "Test that multicast routes propagated and installed"
    tgen = get_topogen()
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    #
    # Test R1 mroute
    #
    expect_1 = {
        "229.1.2.3": {
            "192.168.10.100": {
                "iif": "r1-eth2",
                "flags": "SFT",
                "oil": {
                    "r1-eth0": {"source": "192.168.10.100", "group": "229.1.2.3"},
                    "r1-eth1": None,
                },
            }
        }
    }
    # Create a deep copy of `expect_1`.
    expect_2 = json.loads(json.dumps(expect_1))
    # The route will be either via R2 or R3.
    expect_2["229.1.2.3"]["192.168.10.100"]["oil"]["r1-eth0"] = None
    expect_2["229.1.2.3"]["192.168.10.100"]["oil"]["r1-eth1"] = {
        "source": "192.168.10.100",
        "group": "229.1.2.3",
    }

    def test_r1_mroute():
        "Test r1 multicast routing table function"
        out = tgen.gears["r1"].vtysh_cmd("show ip mroute json", isjson=True)
        if topotest.json_cmp(out, expect_1) is None:
            return None
        return topotest.json_cmp(out, expect_2)

    logger.info("Waiting for R1 multicast routes")
    _, val = topotest.run_and_expect(test_r1_mroute, None, count=55, wait=2)
    assert val is None, "multicast route convergence failure"

    #
    # Test routers 2 and 3.
    #
    # NOTE: only one of the paths will get the multicast route.
    #
    expect_r2 = {
        "229.1.2.3": {
            "192.168.10.100": {
                "iif": "r2-eth0",
                "flags": "S",
                "oil": {
                    "r2-eth1": {
                        "source": "192.168.10.100",
                        "group": "229.1.2.3",
                    }
                },
            }
        }
    }
    expect_r3 = {
        "229.1.2.3": {
            "192.168.10.100": {
                "iif": "r3-eth0",
                "flags": "S",
                "oil": {
                    "r3-eth1": {
                        "source": "192.168.10.100",
                        "group": "229.1.2.3",
                    }
                },
            }
        }
    }

    def test_r2_r3_mroute():
        "Test r2/r3 multicast routing table function"
        r2_out = tgen.gears["r2"].vtysh_cmd("show ip mroute json", isjson=True)
        r3_out = tgen.gears["r3"].vtysh_cmd("show ip mroute json", isjson=True)

        if topotest.json_cmp(r2_out, expect_r2) is not None:
            return topotest.json_cmp(r3_out, expect_r3)

        return topotest.json_cmp(r2_out, expect_r2)

    logger.info("Waiting for R2 and R3 multicast routes")
    _, val = topotest.run_and_expect(test_r2_r3_mroute, None, count=55, wait=2)
    assert val is None, "multicast route convergence failure"

    #
    # Test router 4
    #
    expect_4 = {
        "229.1.2.3": {
            "*": {
                "iif": "lo",
                "flags": "SC",
                "oil": {
                    "pimreg": {
                        "source": "*",
                        "group": "229.1.2.3",
                        "inboundInterface": "lo",
                        "outboundInterface": "pimreg",
                    },
                    "r4-eth2": {
                        "source": "*",
                        "group": "229.1.2.3",
                        "inboundInterface": "lo",
                        "outboundInterface": "r4-eth2",
                    },
                },
            },
            "192.168.10.100": {
                "iif": "r4-eth0",
                "flags": "ST",
                "oil": {
                    "r4-eth2": {
                        "source": "192.168.10.100",
                        "group": "229.1.2.3",
                        "inboundInterface": "r4-eth0",
                        "outboundInterface": "r4-eth2",
                    }
                },
            },
        }
    }

    test_func = partial(
        topotest.router_json_cmp,
        tgen.gears["r4"],
        "show ip mroute json",
        expect_4,
    )
    logger.info("Waiting for R4 multicast routes")
    _, val = topotest.run_and_expect(test_func, None, count=55, wait=2)
    assert val is None, "multicast route convergence failure"


def test_mroute_install():
    tgen = get_topogen()
    # pytest.skip("FOO")
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    logger.info("Starting helper1")
    mcastaddr = "229.1.2.3"
    app_helper.run("h1", [mcastaddr, "h1-eth0"])

    logger.info("Starting helper2")
    app_helper.run("h2", ["--send=0.7", mcastaddr, "h2-eth0"])

    _test_mroute_install()


def test_msdp():
    """
    Test MSDP convergence.

    MSDP non meshed groups must propagate the whole SA database (not just
    their own) to all peers because not all peers talk with each other.

    This setup leads to a potential loop that can be prevented by checking
    the route's first AS in AS path: it must match the remote eBGP AS number.
    """
    tgen = get_topogen()
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    r1_expect = {
        "192.168.0.2": {
            "peer": "192.168.0.2",
            "local": "192.168.0.1",
            "state": "established",
        },
        "192.168.1.2": {
            "peer": "192.168.1.2",
            "local": "192.168.1.1",
            "state": "established",
        },
    }
    r1_sa_expect = {
        "229.1.2.3": {
            "192.168.10.100": {
                "source": "192.168.10.100",
                "group": "229.1.2.3",
                "rp": "-",
                "local": "yes",
                "sptSetup": "-",
            }
        }
    }
    r2_expect = {
        "192.168.0.1": {
            "peer": "192.168.0.1",
            "local": "192.168.0.2",
            "state": "established",
        },
        "192.168.2.2": {
            "peer": "192.168.2.2",
            "local": "192.168.2.1",
            "state": "established",
        },
    }
    # Only R2 or R3 will get this SA.
    r2_r3_sa_expect = {
        "229.1.2.3": {
            "192.168.10.100": {
                "source": "192.168.10.100",
                "group": "229.1.2.3",
                "rp": "10.254.254.1",
                "local": "no",
                "sptSetup": "no",
            }
        }
    }
    r3_expect = {
        "192.168.1.1": {
            "peer": "192.168.1.1",
            "local": "192.168.1.2",
            "state": "established",
        },
        # "192.169.3.2": {
        #    "peer": "192.168.3.2",
        #    "local": "192.168.3.1",
        #    "state": "established"
        # }
    }
    r4_expect = {
        "192.168.2.1": {
            "peer": "192.168.2.1",
            "local": "192.168.2.2",
            "state": "established",
        },
        # "192.168.3.1": {
        #    "peer": "192.168.3.1",
        #    "local": "192.168.3.2",
        #    "state": "established"
        # }
    }
    r4_sa_expect = {
        "229.1.2.3": {
            "192.168.10.100": {
                "source": "192.168.10.100",
                "group": "229.1.2.3",
                "rp": "10.254.254.1",
                "local": "no",
                "sptSetup": "yes",
            }
        }
    }

    for router in [
        ("r1", r1_expect, r1_sa_expect),
        ("r2", r2_expect, r2_r3_sa_expect),
        ("r3", r3_expect, r2_r3_sa_expect),
        ("r4", r4_expect, r4_sa_expect),
    ]:
        test_func = partial(
            topotest.router_json_cmp,
            tgen.gears[router[0]],
            "show ip msdp peer json",
            router[1],
        )
        logger.info("Waiting for {} msdp peer data".format(router[0]))
        _, val = topotest.run_and_expect(test_func, None, count=30, wait=1)
        assert val is None, "multicast route convergence failure"

        test_func = partial(
            topotest.router_json_cmp,
            tgen.gears[router[0]],
            "show ip msdp sa json",
            router[2],
        )
        logger.info("Waiting for {} msdp SA data".format(router[0]))
        _, val = topotest.run_and_expect(test_func, None, count=30, wait=1)
        assert val is None, "multicast route convergence failure"


def test_msdp_sa_filter():
    "Start a number of multicast streams and check if filtering works"

    tgen = get_topogen()

    # Flow from r1 -> r4
    for multicast_address in ["229.2.1.1", "229.2.1.2", "229.2.2.1"]:
        app_helper.run("h1", [multicast_address, "h1-eth0"])
        app_helper.run("h2", ["--send=0.7", multicast_address, "h2-eth0"])

    # Flow from r4 -> r1
    for multicast_address in ["229.3.1.1", "229.3.1.2", "229.3.2.1"]:
        app_helper.run("h1", ["--send=0.7", multicast_address, "h1-eth0"])
        app_helper.run("h2", [multicast_address, "h2-eth0"])

    # Flow from r4 -> r1 but with more sources
    for multicast_address in ["229.10.1.1", "229.11.1.1"]:
        app_helper.run("h1", ["--send=0.7", multicast_address, "h1-eth0"])
        app_helper.run("h2", [multicast_address, "h2-eth0"])
        app_helper.run("h3", ["--send=0.7", multicast_address, "h3-eth0"])

    # Test that we don't learn any filtered multicast streams.
    r4_sa_expected = {
        "229.2.1.1": None,
        "229.2.1.2": None,
        "229.2.2.1": {
            "192.168.10.100": {
                "local": "no",
                "sptSetup": "yes",
            }
        },
    }
    test_func = partial(
        topotest.router_json_cmp,
        tgen.gears["r4"],
        "show ip msdp sa json",
        r4_sa_expected,
    )
    logger.info("Waiting for r4 MDSP SA data")
    _, val = topotest.run_and_expect(test_func, None, count=30, wait=1)
    assert val is None, "multicast route convergence failure"

    # Test that we don't send any filtered multicast streams.
    r1_sa_expected = {
        "229.3.1.1": None,
        "229.3.1.2": None,
        "229.3.2.1": {
            "192.168.4.100": {
                "local": "no",
                "sptSetup": "yes",
            }
        },
        "229.10.1.1": {
            "192.168.4.100": None,
            "192.168.4.120": {
                "local": "no",
                "sptSetup": "yes",
            },
        },
        "229.11.1.1": {
            "192.168.4.100": {
                "local": "no",
                "sptSetup": "yes",
            },
            "192.168.4.120": {
                "local": "no",
                "sptSetup": "yes",
            },
        },
    }
    test_func = partial(
        topotest.router_json_cmp,
        tgen.gears["r1"],
        "show ip msdp sa json",
        r1_sa_expected,
    )
    logger.info("Waiting for r1 MDSP SA data")
    _, val = topotest.run_and_expect(test_func, None, count=30, wait=1)
    assert val is None, "multicast route convergence failure"


def test_msdp_sa_limit():
    "Test MSDP SA limiting."

    tgen = get_topogen()
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    tgen.gears["r4"].vtysh_cmd(
        """
    configure terminal
    router pim
     msdp log sa-events
     msdp peer 192.168.2.1 sa-limit 4
     msdp peer 192.168.3.1 sa-limit 4
    """
    )

    # Flow from r1 -> r4
    for multicast_address in [
        "229.1.2.10",
        "229.1.2.11",
        "229.1.2.12",
        "229.1.2.13",
        "229.1.2.14",
    ]:
        app_helper.run("h1", [multicast_address, "h1-eth0"])
        app_helper.run("h2", ["--send=0.7", multicast_address, "h2-eth0"])

    def test_sa_limit_log():
        r4_log = tgen.gears["r4"].net.getLog("log", "pimd")
        return re.search(r"MSDP peer .+ reject SA (.+, .+): SA limit \d+ of 4", r4_log)

    _, val = topotest.run_and_expect(test_sa_limit_log, None, count=30, wait=1)
    assert val is None, "SA limit check failed"


def test_msdp_log_events():
    "Test that the enabled logs are working as expected."

    tgen = get_topogen()
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    r1_log = tgen.gears["r1"].net.getLog("log", "pimd")

    # Look up for informational messages that should have been enabled.
    match = re.search("MSDP peer 192.168.1.2 state changed to established", r1_log)
    assert match is not None

    match = re.search(r"MSDP SA \(192.168.10.100\,229.1.2.3\) created", r1_log)
    assert match is not None


def test_msdp_shutdown():
    "Shutdown MSDP sessions between r1, r2, r3, then check the state."

    tgen = get_topogen()
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    tgen.gears["r1"].vtysh_cmd(
        """
    configure terminal
    router pim
     msdp shutdown
    """
    )

    r1_expect = {
        "192.168.0.2": {
            "state": "inactive",
        },
        "192.168.1.2": {
            "state": "inactive",
        },
    }
    r2_expect = {
        "192.168.0.1": {
            "state": "listen",
        }
    }
    r3_expect = {
        "192.168.1.1": {
            "state": "listen",
        }
    }
    for router in [("r1", r1_expect), ("r2", r2_expect), ("r3", r3_expect)]:
        test_func = partial(
            topotest.router_json_cmp,
            tgen.gears[router[0]],
            "show ip msdp peer json",
            router[1],
        )
        logger.info("Waiting for {} msdp peer data".format(router[0]))
        _, val = topotest.run_and_expect(test_func, None, count=30, wait=1)
        assert val is None, "multicast route convergence failure"


def test_memory_leak():
    "Run the memory leak test and report results."
    tgen = get_topogen()
    if not tgen.is_memleak_enabled():
        pytest.skip("Memory leak test/report is disabled")

    tgen.report_memory_leaks()


if __name__ == "__main__":
    args = ["-s"] + sys.argv[1:]
    sys.exit(pytest.main(args))
