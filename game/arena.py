"""Arena PvP rules (Version 7) — no Telegram code here.

This module replaces the Version-4 PvE combat system. A duel is always
*player dragon vs another player's dragon*; there are no NPC enemies.

Design notes
------------
* **Dragons never die and never lose stored HP.** The fight runs on a
  simulation copy of each dragon's stats, so the arena cannot break the
  feeding, growth or upgrade systems. The stored ``hp`` column is untouched.
* **Matchmaking** compares a single ``rating`` built from level, power and
  max HP, and additionally caps the raw level gap, so a level-2 dragon is
  never thrown at a level-20 one.
* **The whole fight is resolved in one call** (:func:`simulate`), which keeps
  the handler simple and means there is no "active battle" state to leak.
* Rewards reuse the existing currency and XP systems — no new economy.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from config import (
    ARENA_CRIT_CHANCE,
    ARENA_CRIT_MULTIPLIER,
    ARENA_DAILY_BATTLE_LIMIT,
    ARENA_DAMAGE_LEVEL_BONUS,
    ARENA_DAMAGE_POWER_MAX_FACTOR,
    ARENA_DAMAGE_POWER_MIN_FACTOR,
    ARENA_LEAGUES,
    ARENA_LOSS_OBSIDIAN,
    ARENA_LOSS_POINTS,
    ARENA_LOSS_XP,
    ARENA_MATCH_LEVEL_SPREAD,
    ARENA_MATCH_RATING_RATIO,
    ARENA_MATCH_WIDE_LEVEL_SPREAD,
    ARENA_MATCH_WIDE_RATING_RATIO,
    ARENA_MAX_TURNS,
    ARENA_MIN_DAMAGE,
    ARENA_POINTS_FLOOR,
    ARENA_RANKING_SIZE,
    ARENA_WIN_OBSIDIAN_MAX,
    ARENA_WIN_OBSIDIAN_MIN,
    ARENA_WIN_POINTS,
    ARENA_WIN_XP,
)
from database.connection import get_db
from game.dragons import DragonService, current_hunger, effective_power
from models.arena import ArenaBattleRepository
from models.dragon import Dragon, DragonRepository
from models.player import Player, PlayerRepository

logger = logging.getLogger(__name__)

# Reasons a search / battle can fail (handlers map these to Persian text).
REASON_NO_DRAGON = "no_dragon"
REASON_NO_OPPONENT = "no_opponent"
REASON_LIMIT_REACHED = "limit_reached"
REASON_ERROR = "error"


# --- helpers ----------------------------------------------------------------
def utc_day(now: Optional[float] = None) -> str:
    """The UTC calendar day used to reset the daily battle counter."""
    now = now if now is not None else time.time()
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")


def rating(dragon: Dragon) -> int:
    """A single strength number used for matchmaking.

    Combines the three stats the spec asks for — level, power and HP — into
    one comparable value. Deliberately simple and monotonic: more of any stat
    is always a higher rating.
    """
    return int(dragon.level * 10 + dragon.power * 3 + dragon.max_hp)


def league_for(points: int) -> dict:
    """The league a point total falls into (highest one reached)."""
    current = ARENA_LEAGUES[0]
    for league in ARENA_LEAGUES:
        if points >= league["min_points"]:
            current = league
    return current


def next_league(points: int) -> Optional[dict]:
    """The next league up, or None when already in the top league."""
    for league in ARENA_LEAGUES:
        if points < league["min_points"]:
            return league
    return None


def is_fair_match(
    a: Dragon, b: Dragon, level_spread: int, rating_ratio: float
) -> bool:
    """True when two dragons are close enough in strength to fight."""
    if abs(a.level - b.level) > level_spread:
        return False
    ra, rb = rating(a), rating(b)
    stronger = max(ra, rb)
    if stronger <= 0:
        return True
    return abs(ra - rb) / stronger <= rating_ratio


# --- data carriers ----------------------------------------------------------
@dataclass
class Fighter:
    """A snapshot of one side of the duel (never written back to the DB)."""

    user_id: int
    username: Optional[str]
    dragon_id: int
    name: str
    emoji: str
    level: int
    max_hp: int
    hp: int
    power: int

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class Turn:
    attacker: str
    defender: str
    damage: int
    crit: bool
    defender_hp: int


@dataclass
class ArenaResult:
    ok: bool
    reason: Optional[str] = None
    challenger: Optional[Fighter] = None
    opponent: Optional[Fighter] = None
    winner_id: Optional[int] = None
    turns: list[Turn] = field(default_factory=list)
    # Rewards granted to the player who started the search.
    points_delta: int = 0
    points_total: int = 0
    obsidian: int = 0
    xp: int = 0
    leveled_up: bool = False
    league: dict = field(default_factory=dict)
    league_changed: bool = False
    battles_used: int = 0
    battles_limit: int = ARENA_DAILY_BATTLE_LIMIT
    battle_id: Optional[int] = None

    @property
    def won(self) -> bool:
        return (
            self.winner_id is not None
            and self.challenger is not None
            and self.winner_id == self.challenger.user_id
        )


@dataclass
class RankEntry:
    rank: int
    user_id: int
    username: Optional[str]
    points: int
    wins: int
    losses: int
    league: dict


# --- battle simulation ------------------------------------------------------
def roll_damage(
    attacker: Fighter, rng: Optional[random.Random] = None
) -> tuple[int, bool]:
    """Damage for one hit: power * random factor + a light level bonus.

    Returns ``(damage, was_critical)``. Always at least ``ARENA_MIN_DAMAGE``.
    """
    rng = rng or random
    factor = rng.uniform(
        ARENA_DAMAGE_POWER_MIN_FACTOR, ARENA_DAMAGE_POWER_MAX_FACTOR
    )
    damage = attacker.power * factor + attacker.level * ARENA_DAMAGE_LEVEL_BONUS
    crit = rng.random() < ARENA_CRIT_CHANCE
    if crit:
        damage *= ARENA_CRIT_MULTIPLIER
    return max(ARENA_MIN_DAMAGE, int(round(damage))), crit


def simulate(
    challenger: Fighter,
    opponent: Fighter,
    rng: Optional[random.Random] = None,
) -> tuple[int, list[Turn]]:
    """Fight until one side reaches 0 HP. Returns ``(winner_user_id, turns)``.

    Initiative is decided by a coin flip. ``ARENA_MAX_TURNS`` guarantees termination;
    if it is ever hit, the fighter with the higher remaining HP fraction wins.
    """
    rng = rng or random
    turns: list[Turn] = []
    # Initiative is random. Striking first is a real advantage in an HP race,
    # so always giving it to the challenger would make an even match ~75/25 in
    # favour of whoever pressed the button. Coin-flipping it keeps a mirror
    # match at 50/50.
    if rng.random() < 0.5:
        attacker, defender = opponent, challenger
    else:
        attacker, defender = challenger, opponent

    for _ in range(ARENA_MAX_TURNS):
        damage, crit = roll_damage(attacker, rng)
        defender.hp = max(0, defender.hp - damage)
        turns.append(
            Turn(
                attacker=attacker.name,
                defender=defender.name,
                damage=damage,
                crit=crit,
                defender_hp=defender.hp,
            )
        )
        if not defender.alive:
            return attacker.user_id, turns
        attacker, defender = defender, attacker

    # Timeout: decide on remaining HP fraction (ties go to the opponent, so a
    # stalemate never rewards the person who pressed the button).
    c_frac = challenger.hp / max(1, challenger.max_hp)
    o_frac = opponent.hp / max(1, opponent.max_hp)
    return (challenger.user_id if c_frac > o_frac else opponent.user_id), turns


class ArenaService:
    """Matchmaking, battle resolution, rewards and ranking."""

    def __init__(
        self,
        players: Optional[PlayerRepository] = None,
        dragons: Optional[DragonRepository] = None,
        battles: Optional[ArenaBattleRepository] = None,
        dragon_service: Optional[DragonService] = None,
    ) -> None:
        self.players = players or PlayerRepository()
        self.dragons = dragons or DragonRepository()
        self.battles = battles or ArenaBattleRepository()
        self.dragon_service = dragon_service or DragonService(dragons=self.dragons)

    # --- reads ------------------------------------------------------------
    def active_dragon(self, user_id: int) -> Optional[Dragon]:
        """The player's selected dragon (the one that fights)."""
        dragon_id = self.players.get_active_dragon_id(user_id)
        if dragon_id is None:
            return None
        return self.dragons.get(dragon_id)

    def battles_left(self, user_id: int, now: Optional[float] = None) -> int:
        used = self.players.arena_battles_used(user_id, utc_day(now))
        return max(0, ARENA_DAILY_BATTLE_LIMIT - used)

    def battles_used(self, user_id: int, now: Optional[float] = None) -> int:
        return self.players.arena_battles_used(user_id, utc_day(now))

    def stats(self, user_id: int, now: Optional[float] = None) -> dict:
        """Everything the «🐉 اژدهای من» screen needs."""
        player = self.players.get(user_id)
        dragon = self.active_dragon(user_id)
        points = player.arena_points if player else 0
        return {
            "player": player,
            "dragon": dragon,
            "points": points,
            "wins": player.arena_wins if player else 0,
            "losses": player.arena_losses if player else 0,
            "league": league_for(points),
            "next_league": next_league(points),
            "rank": self.players.arena_rank_of(user_id),
            "used": self.battles_used(user_id, now),
            "limit": ARENA_DAILY_BATTLE_LIMIT,
            "rating": rating(dragon) if dragon else 0,
        }

    def ranking(self, limit: int = ARENA_RANKING_SIZE) -> list[RankEntry]:
        entries: list[RankEntry] = []
        for index, player in enumerate(self.players.top_by_arena_points(limit), start=1):
            entries.append(
                RankEntry(
                    rank=index,
                    user_id=player.user_id,
                    username=player.username,
                    points=player.arena_points,
                    wins=player.arena_wins,
                    losses=player.arena_losses,
                    league=league_for(player.arena_points),
                )
            )
        return entries

    # --- matchmaking ------------------------------------------------------
    def _fighter(
        self, player: Player, dragon: Dragon, now: float
    ) -> Fighter:
        """Snapshot a dragon for the fight, applying the hunger penalty.

        Hunger already scales power everywhere else in the game, so the arena
        honours it too — a starving dragon fights weaker. Stored stats are not
        modified.
        """
        from game.dragons import dragon_type_display

        hunger = current_hunger(dragon, now)
        _, emoji = dragon_type_display(dragon.dragon_type)
        return Fighter(
            user_id=player.user_id,
            username=player.username,
            dragon_id=dragon.id,
            name=dragon.name,
            emoji=emoji,
            level=dragon.level,
            max_hp=dragon.max_hp,
            hp=dragon.max_hp,  # everyone enters the arena at full strength
            power=max(1, effective_power(dragon.power, hunger)),
        )

    def find_opponent(
        self, user_id: int, rng: Optional[random.Random] = None
    ) -> Optional[tuple[Player, Dragon]]:
        """Pick a player whose active dragon is a fair match.

        Tries a strict window first, then one wider window so that small
        groups can still find a fight. Never returns a wildly unfair pair.
        """
        rng = rng or random
        mine = self.active_dragon(user_id)
        if mine is None:
            return None

        candidates: list[tuple[Player, Dragon]] = []
        for player in self.players.arena_candidates(user_id):
            if player.active_dragon_id is None:
                continue
            dragon = self.dragons.get(player.active_dragon_id)
            if dragon is None or dragon.owner_id != player.user_id:
                continue
            candidates.append((player, dragon))

        if not candidates:
            return None

        windows = (
            (ARENA_MATCH_LEVEL_SPREAD, ARENA_MATCH_RATING_RATIO),
            (ARENA_MATCH_WIDE_LEVEL_SPREAD, ARENA_MATCH_WIDE_RATING_RATIO),
        )
        for level_spread, rating_ratio in windows:
            pool = [
                pair
                for pair in candidates
                if is_fair_match(mine, pair[1], level_spread, rating_ratio)
            ]
            if pool:
                # Prefer the closest rating, breaking ties randomly so the same
                # two players do not always meet.
                target = rating(mine)
                best = min(abs(rating(d) - target) for _, d in pool)
                closest = [p for p in pool if abs(rating(p[1]) - target) == best]
                return rng.choice(closest)
        return None

    # --- the duel ---------------------------------------------------------
    def fight(
        self,
        user_id: int,
        chat_id: Optional[int] = None,
        rng: Optional[random.Random] = None,
        now: Optional[float] = None,
    ) -> ArenaResult:
        """Run one full arena battle for ``user_id`` and apply the rewards.

        Returns an :class:`ArenaResult`; on failure ``ok`` is False and
        ``reason`` says why. A battle slot is only consumed once an opponent
        has actually been found, so a failed search never costs the player.
        """
        rng = rng or random
        now = now if now is not None else time.time()

        player = self.players.get(user_id)
        if player is None:
            return ArenaResult(ok=False, reason=REASON_NO_DRAGON)

        mine = self.active_dragon(user_id)
        if mine is None:
            return ArenaResult(ok=False, reason=REASON_NO_DRAGON)

        # Daily limit is checked (but not yet consumed) before searching.
        limit_left = self.battles_left(user_id, now)
        if limit_left <= 0:
            return ArenaResult(
                ok=False,
                reason=REASON_LIMIT_REACHED,
                battles_used=ARENA_DAILY_BATTLE_LIMIT,
            )

        match = self.find_opponent(user_id, rng=rng)
        if match is None:
            return ArenaResult(ok=False, reason=REASON_NO_OPPONENT)
        rival, rival_dragon = match

        # Claim the slot only now that a real fight is going to happen.
        allowed, used = self.players.consume_arena_battle(
            user_id, utc_day(now), ARENA_DAILY_BATTLE_LIMIT
        )
        if not allowed:
            return ArenaResult(
                ok=False, reason=REASON_LIMIT_REACHED, battles_used=used
            )

        challenger = self._fighter(player, mine, now)
        opponent = self._fighter(rival, rival_dragon, now)
        # Keep the entry stats for the "VS" card before HP starts dropping.
        card_challenger = Fighter(**challenger.__dict__)
        card_opponent = Fighter(**opponent.__dict__)

        winner_id, turns = simulate(challenger, opponent, rng=rng)
        won = winner_id == user_id

        points_before = player.arena_points
        league_before = league_for(points_before)

        if won:
            points_delta = ARENA_WIN_POINTS
            obsidian = rng.randint(ARENA_WIN_OBSIDIAN_MIN, ARENA_WIN_OBSIDIAN_MAX)
            xp_amount = ARENA_WIN_XP
        else:
            points_delta = -ARENA_LOSS_POINTS
            obsidian = ARENA_LOSS_OBSIDIAN
            xp_amount = ARENA_LOSS_XP

        # Apply rewards. Currency and the arena record move together; XP goes
        # through the normal growth system so level-ups behave as everywhere
        # else. The dragon's HP is never written — nobody dies in the arena.
        with get_db() as conn:
            points_total = self.players.record_arena_result(
                user_id,
                won=won,
                points_delta=points_delta,
                points_floor=ARENA_POINTS_FLOOR,
                conn=conn,
            )
            if obsidian:
                self.players.add_resources(user_id, obsidian=obsidian, conn=conn)
            # The opponent is a passive participant: their record is updated so
            # the ladder stays consistent, but they get no currency.
            self.players.record_arena_result(
                rival.user_id,
                won=not won,
                points_delta=(-ARENA_LOSS_POINTS if won else ARENA_WIN_POINTS),
                points_floor=ARENA_POINTS_FLOOR,
                conn=conn,
            )

        xp_result = self.dragon_service.add_xp(mine.id, xp_amount) if xp_amount else None

        battle_id = self.battles.record(
            challenger_id=user_id,
            opponent_id=rival.user_id,
            challenger_dragon_id=mine.id,
            opponent_dragon_id=rival_dragon.id,
            winner_id=winner_id,
            turns=len(turns),
            chat_id=chat_id,
            log=[
                {
                    "a": t.attacker,
                    "d": t.defender,
                    "dmg": t.damage,
                    "crit": t.crit,
                    "hp": t.defender_hp,
                }
                for t in turns
            ],
            reward={"points": points_delta, "obsidian": obsidian, "xp": xp_amount},
            now=now,
        )

        league_after = league_for(points_total)
        return ArenaResult(
            ok=True,
            challenger=card_challenger,
            opponent=card_opponent,
            winner_id=winner_id,
            turns=turns,
            points_delta=points_delta,
            points_total=points_total,
            obsidian=obsidian,
            xp=xp_amount,
            leveled_up=bool(xp_result and xp_result.leveled_up),
            league=league_after,
            league_changed=league_after["key"] != league_before["key"],
            battles_used=used,
            battles_limit=ARENA_DAILY_BATTLE_LIMIT,
            battle_id=battle_id,
        )


def summarise_turns(turns: Sequence[Turn], keep: int = 6) -> list[Turn]:
    """Trim a long fight log so the battle message stays short."""
    if len(turns) <= keep:
        return list(turns)
    # Keep the opening exchanges and the finish — that is the readable part.
    head = keep - 2
    return list(turns[:head]) + list(turns[-2:])
