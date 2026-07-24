package com.sal0.karaoke;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class ConnectionRouterTest {
    @Test
    public void configuredWifiPrefersLocal() {
        assertEquals(
            ConnectionRouter.Route.LOCAL,
            ConnectionRouter.priority(true, "\"Minha Casa\"", "minha casa").get(0)
        );
    }

    @Test
    public void mobileNetworkPrefersExternal() {
        assertEquals(
            ConnectionRouter.Route.EXTERNAL,
            ConnectionRouter.priority(false, "", "Minha Casa").get(0)
        );
    }

    @Test
    public void unknownWifiTriesLocalBeforeExternal() {
        assertEquals(
            ConnectionRouter.Route.LOCAL,
            ConnectionRouter.priority(true, "<unknown ssid>", "Minha Casa").get(0)
        );
    }
}
