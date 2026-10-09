"""A small simulation of a WMS WebControl box for integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util


def _local_now() -> datetime:
    """HA's local time without time zone, like the box clock."""
    return dt_util.now().replace(tzinfo=None)


def timer_block(enabled: int = 1, entries=()) -> list[int]:
    """199-value timer block; entries = (day, slot, hour, minute, pos_raw, comfort)."""
    block = [54, enabled, 1] + [255] * (199 - 3)
    for day in range(7):
        for slot in range(4):
            block[3 + day * 28 + slot * 7 + 6] = 2
    for day, slot, hour, minute, pos, comfort in entries:
        base = 3 + day * 28 + slot * 7
        block[base : base + 7] = [hour, minute, pos, 255, 255, 255, comfort]
    return block


USER_TIMER = timer_block(entries=[(d, 0, 18, 30, 0, 1) for d in range(7)])


def xml(body: str) -> str:
    return f"<?xml version='1.0' encoding='utf-8'?><response>{body}</response>"


@dataclass
class FakeBox:
    """Answers protocol.xml queries; records every payload it receives."""

    rooms: dict[int, str] = field(default_factory=lambda: {0: "Balkon"})
    channels: dict[tuple[int, int], tuple[str, int, int, int]] = field(
        default_factory=lambda: {
            (0, 0): ("Markise", 255, 3, 4),
            (0, 1): ("60% raus", 2, 255, 255),
            (0, 2): ("100 % raus", 0, 255, 255),
            (0, 3): ("Markise einfahren", 1, 255, 255),
        }
    )
    position: int = 0  # raw 0..200
    reachable: bool = True
    reject_next_operations: int = 0  # answer 0x21 with "stack busy, feedback 0"
    payloads: list[bytes] = field(default_factory=list)
    clock_drift: float = 0.0  # seconds the box clock is ahead of the real time
    time_master: int = 1
    timer: list[int] = field(default_factory=lambda: list(USER_TIMER))
    timer_failures: int = 0  # answer the next timer reads with "actor did not answer"
    _pending: dict[tuple[int, int, int], bool] = field(default_factory=dict)

    async def fetch(self, query: str) -> str:
        from custom_components.wms_webcontrol.client import WmsConnectionError

        if not self.reachable:
            raise WmsConnectionError("ConnectTimeoutError: simulated")
        frame = bytes.fromhex(query.split("protocol=", 1)[1].split("&", 1)[0])
        assert frame[0] == 0x90 and frame[1] != 0xFF and frame[2] == len(frame) - 3
        payload = frame[3:]
        self.payloads.append(payload)
        tel = payload[0]
        if tel == 0x03:
            return xml(f"<responseID>4</responseID><raumname>{self.rooms.get(payload[1], '')}</raumname>")
        if tel == 0x47:
            info = self.channels.get((payload[1], payload[2]))
            if info is None:
                return xml("<responseID>72</responseID><kanalname></kanalname>")
            name, scene, ptype, otype = info
            return xml(
                f"<responseID>72</responseID><kanalname>{name}</kanalname>"
                f"<szeneindex>{scene}</szeneindex><produkttyp>{ptype}</produkttyp>"
                f"<bedientyp>{otype}</bedientyp>"
            )
        if tel == 0x23:
            self._pending[(payload[1], payload[2], 1)] = True
            return xml("<responseID>51</responseID><requestid>35</requestid><feedback>1</feedback>")
        if tel == 0x21:
            if self.reject_next_operations:
                self.reject_next_operations -= 1
                return xml("<responseID>51</responseID><requestid>33</requestid><feedback>0</feedback>")
            fc = payload[3]
            if fc == 3 and payload[4] != 0xFF:
                self.position = payload[4]
            if fc == 8:
                self.position = {1: 120, 2: 200, 3: 0}.get(payload[2], self.position)
            self._pending[(payload[1], payload[2], 0)] = True
            return xml("<responseID>51</responseID><requestid>33</requestid><feedback>1</feedback>")
        if tel == 0x2F:
            if payload[1] == 1:
                _, _, master, day, month, year, hour, minute, second = payload
                box = datetime(2000 + year, month, day, hour, minute, second)
                self.clock_drift = (box - _local_now()).total_seconds()
                self.time_master = master
            now = _local_now() + timedelta(seconds=self.clock_drift)
            return xml(
                f"<responseID>48</responseID><senden>{self.time_master}</senden>"
                f"<tag>{now.day}</tag><monat>{now.month}</monat><jahr>{now.year % 100}</jahr>"
                f"<stunden>{now.hour}</stunden><minuten>{now.minute}</minuten>"
                f"<sekunden>{now.second}</sekunden>"
            )
        if tel == 0x4D:
            self._pending[(payload[1], payload[2], 9)] = True
            return xml("<responseID>51</responseID><requestid>77</requestid><feedback>1</feedback>")
        if tel == 0x63:
            area = payload[3]
            padded = self.timer + [255] * (220 - len(self.timer))
            values = ",".join(str(v) for v in padded[area * 22 : (area + 1) * 22])
            return xml(f"<responseID>100</responseID><parameter>{values}</parameter>")
        if tel == 0x25:
            return xml("<responseID>51</responseID><requestid>37</requestid><feedback>1</feedback>")
        if tel == 0x31:
            key = (payload[1], payload[2], payload[3])
            if not self._pending.pop(key, False):
                return xml("<responseID>52</responseID><requestid>49</requestid><errorcode>32</errorcode>")
            if payload[3] == 9:
                if self.timer_failures:
                    self.timer_failures -= 1
                    return xml("<responseID>50</responseID><befehl>9</befehl><feedback>2</feedback>")
                return xml("<responseID>78</responseID>")
            if payload[3] == 0:
                return xml(
                    f"<responseID>34</responseID><raumindex>{payload[1]}</raumindex>"
                    f"<kanalindex>{payload[2]}</kanalindex><feedback>0</feedback>"
                )
            return xml(
                f"<responseID>36</responseID><raumindex>{payload[1]}</raumindex>"
                f"<kanalindex>{payload[2]}</kanalindex><fahrt>0</fahrt>"
                f"<position>{self.position}</position><winkel>255</winkel>"
                "<positionvolant1>255</positionvolant1><positionvolant2>255</positionvolant2>"
            )
        raise AssertionError(f"unexpected telegram 0x{tel:02x}")

    def operations(self) -> list[str]:
        return [p.hex() for p in self.payloads if p[0] == 0x21]

    def clock_writes(self) -> list[bytes]:
        return [p for p in self.payloads if p[0] == 0x2F and p[1] == 1]
