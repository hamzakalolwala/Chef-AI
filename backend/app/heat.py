"""Heat sources and pots: how fast water, milk or oil heats on LPG vs induction.

A lumped thermal model (one temperature for the contents, one for the pot) stepped once per second:

    heat into pot   = input power × efficiency × duty            (induction pulses on/off at low levels)
    pot -> contents = conductance × (T_pot - T_contents)
    losses          = h·A × (T - room) + evaporation once water reaches 100 °C
    hot spot        = how much hotter the hottest patch of the base is than the average

LPG vs induction (typical Indian domestic values, approximate):
    LPG             1.2 kW small / 2.2 kW large burner, ~60 % into the pot (BIS-rated stoves test ≥ 68 % with
                    a matched vessel; real pans waste more). About a quarter of it wraps up the pot's sides,
                    and the flame ring makes a hot ring on thin steel.
    Induction       up to ~2 kW, ~85 % into the pot, base only. Many models pulse on/off below ~800 W.
                    Needs a magnetic pot (steel / cast iron): plain aluminium or copper won't heat.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

ROOM = 28.0  # °C, Indian kitchen


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    kind: str                 # "lpg" | "induction"
    max_watts: float
    efficiency: float
    side_fraction: float      # share of delivered heat that goes into the pot's walls (gas wraps around)
    pattern: float            # how concentrated the heat is on the base (1 = gas ring, lower = spread)
    levels: int = 10          # knob positions / power levels

    def watts(self, level: float) -> tuple[float, float]:
        """(average input watts, duty cycle) at a power level 1..levels."""
        level = max(0.0, min(self.levels, level))
        if level == 0:
            return 0.0, 0.0
        if self.kind == "lpg":
            # gas knob: sim ~15 % of full flame, smooth in between
            return self.max_watts * (0.15 + 0.85 * (level - 1) / (self.levels - 1)), 1.0
        target = self.max_watts * level / self.levels
        if target < 800:                     # cheap induction can't run steadily below ~800 W: it pulses
            return target, target / 800
        return target, 1.0


SOURCES = {
    "lpg_small": Source("lpg_small", "LPG small burner", "lpg", 1200, 0.60, 0.25, 1.0),
    "lpg_large": Source("lpg_large", "LPG large burner", "lpg", 2200, 0.58, 0.28, 1.0),
    "induction": Source("induction", "Induction (2000 W)", "induction", 2000, 0.85, 0.0, 0.6),
}


@dataclass(frozen=True)
class Vessel:
    id: str
    name: str
    material: str
    heat_capacity: float      # J/K of the empty pot
    spread: float             # how evenly the base spreads heat (lower = more even)
    induction_ok: bool
    area_m2: float            # exposed surface for losses
    conductance: float        # W/K pot -> contents


VESSELS = {
    "steel_saucepan": Vessel("steel_saucepan", "Steel saucepan (chai pan)", "steel", 300, 1.0, True, 0.035, 180),
    "aluminium_pan": Vessel("aluminium_pan", "Aluminium pan", "aluminium", 330, 0.45, False, 0.035, 260),
    "triply_pan": Vessel("triply_pan", "Tri-ply steel pan", "triply", 420, 0.5, True, 0.04, 230),
    "iron_kadhai": Vessel("iron_kadhai", "Cast-iron kadhai", "iron", 900, 0.6, True, 0.07, 200),
    "nonstick_pan": Vessel("nonstick_pan", "Non-stick pan (induction base)", "aluminium", 350, 0.5, True, 0.05, 220),
}

CP = {"water": 4186.0, "milk": 3930.0, "oil": 1970.0, "ghee": 2100.0}   # J/(kg·K)
BOIL = {"water": 100.0, "milk": 100.5}
LATENT = 2.26e6                                                     # J/kg to evaporate water


@dataclass
class Pot:
    """Contents (grams by liquid kind) + vessel + heat source, stepped through time."""
    vessel: Vessel
    source: Source
    contents: dict[str, float] = field(default_factory=dict)
    t_contents: float = ROOM
    t_pot: float = ROOM
    lid: bool = False
    evaporated_g: float = 0.0
    time_s: float = 0.0
    log: list[tuple[float, float, float, float]] = field(default_factory=list)  # (t, T_contents, T_hotspot, watts)

    @property
    def mass_kg(self) -> float:
        return sum(self.contents.values()) / 1000

    @property
    def heat_capacity(self) -> float:
        return sum(g / 1000 * CP.get(k, 3500.0) for k, g in self.contents.items())

    @property
    def watery(self) -> bool:
        return self.contents.get("water", 0) + self.contents.get("milk", 0) > self.contents.get("oil", 0) + \
            self.contents.get("ghee", 0)

    def heats(self) -> bool:
        return self.source.kind != "induction" or self.vessel.induction_ok

    def add(self, kind: str, grams: float, temp: float = ROOM) -> None:
        """Pour something in: contents temperature mixes by heat capacity."""
        c_before = self.heat_capacity
        c_add = grams / 1000 * CP.get(kind, 3500.0)
        if c_before + c_add > 0:
            self.t_contents = (self.t_contents * c_before + temp * c_add) / (c_before + c_add)
        self.contents[kind] = self.contents.get(kind, 0.0) + grams

    def step(self, level: float, dt: float = 1.0) -> None:
        watts, duty = self.source.watts(level)
        delivered = watts * self.source.efficiency if self.heats() else 0.0
        # Induction below ~800 W pulses: full power part of each ~10 s cycle (same average, peakier base).
        q_pot = delivered
        c_pot = self.vessel.heat_capacity
        c_in = max(self.heat_capacity, 1.0)
        loss_pot = 6.0 * self.vessel.area_m2 * 10 * (self.t_pot - ROOM)      # outside of the pot
        h_top = 4.0 if self.lid else 12.0                                     # W/(m²K) at the surface
        loss_top = h_top * self.vessel.area_m2 * (self.t_contents - ROOM)
        self.t_pot += (q_pot - loss_pot) / c_pot * dt
        self.t_contents -= loss_top / c_in * dt
        # Pot <-> contents exchange, solved exactly (a tiny splash of oil in a heavy kadhai would make a
        # simple step overshoot): the gap shrinks as exp(-G·(1/Cpot + 1/Cin)·dt), energy is conserved.
        gap = self.t_pot - self.t_contents
        new_gap = gap * math.exp(-self.vessel.conductance * (1 / c_pot + 1 / c_in) * dt)
        moved = (gap - new_gap) * c_pot * c_in / (c_pot + c_in)
        self.t_pot -= moved / c_pot
        self.t_contents += moved / c_in
        # Water-based contents can't pass boiling: the extra energy evaporates water.
        boil = BOIL["milk"] if self.contents.get("milk") else BOIL["water"]
        if self.watery and self.t_contents > boil:
            excess_j = (self.t_contents - boil) * c_in
            grams = min(self.contents.get("water", 0) + self.contents.get("milk", 0) * 0.87,
                        excess_j / LATENT * 1000 * (0.35 if self.lid else 1.0))
            self.evaporated_g += grams
            take = "water" if self.contents.get("water", 0) >= grams else "milk"
            self.contents[take] = max(0.0, self.contents.get(take, 0) - grams)
            self.t_contents = boil
            self.t_pot = min(self.t_pot, boil + 25)
        self.time_s += dt
        self.log.append((self.time_s, round(self.t_contents, 2), round(self.hotspot(level), 1), round(watts, 0)))

    def hotspot(self, level: float) -> float:
        """Hottest patch of the base (where milk catches and spices scorch)."""
        watts, duty = self.source.watts(level)
        peak = watts / duty if duty > 0 else 0.0          # pulsing induction runs at full power when on
        delivered = peak * self.source.efficiency * (1 - self.source.side_fraction) if self.heats() else 0.0
        thin = 1.0 if self.watery else 2.2                # little liquid (tadka, roasting) -> hotter spots
        return max(self.t_pot, self.t_contents) + 0.012 * delivered * self.source.pattern * self.vessel.spread * thin

    def run_until(self, level: float, target_c: float, max_s: float = 1800) -> float:
        """Heat at `level` until contents reach target_c (or max_s). Returns seconds taken."""
        start = self.time_s
        while self.t_contents < target_c - 0.05 and self.time_s - start < max_s:
            self.step(level)
            if self.watery and self.t_contents >= (BOIL["milk"] if self.contents.get("milk") else 100) - 0.05 \
                    and target_c >= 100:
                break
        return self.time_s - start

    def run_for(self, level: float, seconds: float) -> None:
        for _ in range(int(seconds)):
            self.step(level)


def time_to_boil(source_id: str, vessel_id: str, water_g: float, level: float | None = None) -> float | None:
    s, v = SOURCES[source_id], VESSELS[vessel_id]
    pot = Pot(v, s, {"water": water_g})
    if not pot.heats():
        return None
    return pot.run_until(level if level is not None else s.levels, 100)
