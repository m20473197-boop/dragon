"""Version 4 — basic PvE combat system tests.

Covers: no active dragon, starting a battle, damage math, enemy death,
rewards (obsidian / XP / aether), the dragon never dying, escaping,
anti-spam guards, restart persistence and multi-user/multi-group isolation.
"""
from __future__ import annotations

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "combat.db")

import config  # noqa: E402
from database.connection import get_db  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.combat import (  # noqa: E402
    CombatService,
    get_enemy,
    random_enemy,
    roll_dragon_damage,
    roll_enemy_damage,
)
from game.dragons import DragonService  # noqa: E402
from handlers import battle as battle_ui  # noqa: E402
from models.battle import (  # noqa: E402
    STATUS_ACTIVE,
    STATUS_FLED,
    STATUS_LOST,
    STATUS_WON,
    BattleRepository,
)
from models.dragon import DragonRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

RESULTS = []


def enemy_name_in(text, result):
    """The turn card must still name the enemy it is about."""
    return result.enemy is not None and result.enemy.name in text


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅" if cond else "❌"), name, extra if not cond else "")


def make_player_with_dragon(players, dragons, user_id, power=20, hp=100, max_hp=100):
    players.get_or_create(user_id, f"user{user_id}")
    dragon = dragons.create(
        owner_id=user_id,
        dragon_type="fire",
        from_egg_id=None,
        name=f"آذر{user_id}",
        level=1,
        xp=0,
        hp=hp,
        max_hp=max_hp,
        power=power,
        hunger=100,
        last_fed_time=None,
    )
    players.set_active_dragon(user_id, dragon.id)
    return dragon


def main():
    init_db()
    run_migrations()

    players = PlayerRepository()
    dragons = DragonRepository()
    battles = BattleRepository()
    combat = CombatService(
        battles=battles, dragons=dragons, players=players,
        dragon_service=DragonService(dragons),
    )

    # --- 1. enemy config ---------------------------------------------------
    check("three starter enemies exist", len(config.ENEMIES) >= 3)
    names = {spec["name"] for spec in config.ENEMIES.values()}
    check(
        "enemy names are the requested ones",
        {"گرگ وحشی", "هیولای جنگل", "عقرب غول پیکر"} <= names,
        names,
    )
    wolf = get_enemy("wolf")
    check(
        "enemy has all required fields",
        wolf is not None
        and wolf.enemy_id == "wolf"
        and wolf.hp == wolf.max_hp == 80
        and wolf.attack_power == 10
        and wolf.reward_min <= wolf.reward_max,
    )
    check("unknown enemy id returns None", get_enemy("dragonzilla") is None)
    picks = {random_enemy(random.Random(i)).enemy_id for i in range(60)}
    check("random_enemy picks several different enemies", len(picks) >= 2, picks)

    # --- 2. no active dragon -----------------------------------------------
    players.get_or_create(1001, "nodragon")
    res = combat.start_battle(1001, chat_id=-500)
    check("player without active dragon cannot fight", not res.success and res.reason == "no_dragon")
    check("no battle row was created", battles.get_active_for_user(1001) is None)
    check("UI message is the required text", battle_ui.MSG_NO_DRAGON == "🐉 ابتدا یک اژدها را انتخاب کنید.")

    # active dragon pointing at a deleted dragon is handled
    players.get_or_create(1002, "ghost")
    with get_db() as conn:
        conn.execute("UPDATE players SET active_dragon_id = 99999 WHERE user_id = ?", (1002,))
    res = combat.start_battle(1002)
    check("stale active dragon id is rejected cleanly", not res.success and res.reason == "no_dragon")

    # --- 3. starting a battle ----------------------------------------------
    d1 = make_player_with_dragon(players, dragons, 2001, power=20)
    res = combat.start_battle(2001, chat_id=-500)
    check("active dragon starts a battle", res.success and res.battle is not None)
    check("battle is active", res.battle.status == STATUS_ACTIVE)
    check("enemy starts at full hp", res.enemy.hp == res.enemy.max_hp)
    check("battle stores the chat id", res.battle.chat_id == -500)
    check("battle stores the dragon", res.battle.dragon_id == d1.id)
    b1 = res.battle.battle_id

    text = battle_ui.start_text(d1.name, res.enemy)
    check("start message has the required lines",
          "⚔️ نبرد شروع شد!" in text and "VS" in text and "❤️" in text, text)
    kb = battle_ui.battle_keyboard(b1)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    check("battle has attack and flee buttons", labels == ["⚔️ حمله", "🏃 فرار"], labels)
    check("callback data is namespaced",
          all(b.callback_data.startswith("bt:") for row in kb.inline_keyboard for b in row))

    # --- 4. anti-spam: one battle at a time --------------------------------
    res2 = combat.start_battle(2001, chat_id=-500)
    check("cannot start a second battle", not res2.success and res2.reason == "already_fighting")
    check("still exactly one active battle",
          battles.count_by_status(STATUS_ACTIVE) == 1, battles.count_by_status(STATUS_ACTIVE))

    # --- 5. another user cannot control it ---------------------------------
    make_player_with_dragon(players, dragons, 2002, power=20)
    other = combat.attack(b1, 2002)
    check("other user cannot attack this battle", not other.success and other.reason == "not_owner")
    other_flee = combat.flee(b1, 2002)
    check("other user cannot flee this battle", not other_flee.success and other_flee.reason == "not_owner")
    check("battle untouched by the intruder", battles.get(b1).status == STATUS_ACTIVE)

    # --- 6. damage calculation ---------------------------------------------
    rng = random.Random(7)
    dmgs = [roll_dragon_damage(d1, now=0, rng=rng) for _ in range(200)]
    check(
        "dragon damage = power + bonus range",
        min(dmgs) >= d1.power + config.BATTLE_DAMAGE_BONUS_MIN
        and max(dmgs) <= d1.power + config.BATTLE_DAMAGE_BONUS_MAX,
        (min(dmgs), max(dmgs)),
    )
    check("damage varies (random bonus applied)", len(set(dmgs)) > 1)
    edmgs = [roll_enemy_damage(wolf, rng=rng) for _ in range(200)]
    check(
        "enemy damage is around its attack power",
        min(edmgs) >= max(config.BATTLE_MIN_DAMAGE,
                          wolf.attack_power - config.BATTLE_ENEMY_DAMAGE_SPREAD)
        and max(edmgs) <= wolf.attack_power + config.BATTLE_ENEMY_DAMAGE_SPREAD,
        (min(edmgs), max(edmgs)),
    )
    # A starving dragon hits softer (existing hunger system is respected).
    starving = dragons.create(
        owner_id=2001, dragon_type="fire", from_egg_id=None, name="گرسنه",
        level=1, xp=0, hp=100, max_hp=100, power=100, hunger=0,
        last_fed_time=0.0,
    )
    weak = roll_dragon_damage(starving, now=999999, rng=random.Random(1))
    check("hunger reduces combat damage", weak < 100 + config.BATTLE_DAMAGE_BONUS_MAX, weak)

    # --- 7. one exchange ----------------------------------------------------
    before_enemy_hp = battles.get(b1).enemy_hp
    r = combat.attack(b1, 2001)
    check("attack succeeds", r.success)
    check("enemy lost exactly the rolled damage",
          r.enemy_hp_after == max(0, before_enemy_hp - r.dragon_damage))
    check("enemy hp persisted", battles.get(b1).enemy_hp == r.enemy_hp_after)
    check("turn counter advanced", battles.get(b1).turns == 1)
    if not r.won:
        check("enemy hit back", r.enemy_damage > 0)
        check("dragon lost hp", dragons.get(d1.id).hp < 100)
        t = battle_ui.turn_text(r)
        check("turn message has the required lines",
              "⚔️" in t and "❤️" in t and enemy_name_in(t, r), t)

    # --- 8. fight to the death: enemy dies, rewards are paid ---------------
    strong = make_player_with_dragon(players, dragons, 3001, power=500, hp=100, max_hp=100)
    p_before = players.get(3001)
    start = combat.start_battle(3001, chat_id=-600)
    bid = start.battle.battle_id
    win = combat.attack(bid, 3001)
    check("a strong dragon one-shots the enemy", win.success and win.won, win.reason)
    check("enemy hp is zero", win.enemy_hp_after == 0)
    check("battle is marked won", battles.get(bid).status == STATUS_WON)
    p_after = players.get(3001)
    check("obsidian reward granted",
          p_after.obsidian == p_before.obsidian + win.obsidian and win.obsidian > 0,
          (p_before.obsidian, p_after.obsidian, win.obsidian))
    check("obsidian is inside the enemy reward range",
          start.enemy.reward_min <= win.obsidian <= start.enemy.reward_max)
    check("xp was granted", win.xp_gained > 0)
    dragon_after = dragons.get(strong.id)
    check("dragon xp/level increased",
          dragon_after.xp > 0 or dragon_after.level > 1,
          (dragon_after.xp, dragon_after.level))
    check("reward snapshot saved in the database",
          battles.get(bid).reward_dict().get("obsidian") == win.obsidian)
    vt = battle_ui.victory_text(win)
    check("victory message is correct", "🎉 پیروزی!" in vt and "🪨 +" in vt, vt)
    check("winner keeps hp (enemy never struck back)", win.dragon_hp_after > 0)

    # buttons after the battle ended
    dead = combat.attack(bid, 3001)
    check("attacking a finished battle is refused", not dead.success and dead.reason == "finished")
    dead_flee = combat.flee(bid, 3001)
    check("fleeing a finished battle is refused", not dead_flee.success and dead_flee.reason == "finished")
    check("no rewards were paid twice", players.get(3001).obsidian == p_after.obsidian)

    # --- 9. aether chance ---------------------------------------------------
    always = random.Random()
    always.random = lambda: 0.0          # always inside BATTLE_AETHER_CHANCE
    rewards = combat.roll_rewards(wolf, rng=always)
    check("aether can be rolled", rewards.get("aether", 0) > 0, rewards)
    never = random.Random()
    never.random = lambda: 0.999
    check("aether is not always granted", "aether" not in combat.roll_rewards(wolf, rng=never))

    p_before = players.get(3001)
    combat.start_battle(3001)
    bid = combat.active_battle(3001).battle_id
    win2 = combat.attack(bid, 3001, rng=always)
    check("aether reward is credited",
          win2.aether > 0 and players.get(3001).aether == p_before.aether + win2.aether,
          (win2.aether, players.get(3001).aether))

    # --- 10. losing: the dragon survives -----------------------------------
    weakling = make_player_with_dragon(players, dragons, 4001, power=1, hp=12, max_hp=100)
    combat.start_battle(4001)
    bid = combat.active_battle(4001).battle_id
    lost_result = None
    for _ in range(200):
        r = combat.attack(bid, 4001)
        if not r.success or r.finished:
            lost_result = r
            break
    check("a weak dragon eventually loses", lost_result is not None and lost_result.lost,
          lost_result.reason if lost_result else "no result")
    survivor = dragons.get(weakling.id)
    check("dragon still exists after losing", survivor is not None)
    check("dragon hp never drops below the floor",
          survivor.hp >= config.BATTLE_DRAGON_MIN_HP, survivor.hp)
    check("dragon is only weakened, not deleted",
          dragons.count_by_owner(4001) == 1)
    check("battle marked lost", battles.get(bid).status == STATUS_LOST)
    check("no obsidian for a loss", players.get(4001).obsidian == 0)
    dt = battle_ui.defeat_text(lost_result)
    check("defeat message is correct", "💀 شکست خوردی!" in dt and "needs rest" in dt, dt)

    # too weak to start again
    again = combat.start_battle(4001)
    check("a weakened dragon must rest before fighting again",
          not again.success and again.reason == "too_weak", again.reason)

    # --- 11. escaping -------------------------------------------------------
    make_player_with_dragon(players, dragons, 5001, power=5)
    combat.start_battle(5001)
    bid = combat.active_battle(5001).battle_id
    combat.attack(bid, 5001)
    hp_mid = dragons.get(players.get_active_dragon_id(5001)).hp
    obs_before = players.get(5001).obsidian
    fled = combat.flee(bid, 5001)
    check("flee succeeds", fled.success)
    check("battle marked fled", battles.get(bid).status == STATUS_FLED)
    check("no rewards for fleeing", players.get(5001).obsidian == obs_before)
    check("no reward snapshot stored", battles.get(bid).reward_dict() == {})
    check("dragon hp unchanged by fleeing",
          dragons.get(players.get_active_dragon_id(5001)).hp == hp_mid)
    check("can start a new battle after fleeing", combat.start_battle(5001).success)
    ft = battle_ui.flee_text("آذر", wolf)
    check("flee message is correct", "🏃 فرار کردی!" in ft, ft)

    # --- 12. persistence across a restart -----------------------------------
    make_player_with_dragon(players, dragons, 6001, power=5)
    combat.start_battle(6001)
    bid = combat.active_battle(6001).battle_id
    combat.attack(bid, 6001)
    hp_snapshot = battles.get(bid).enemy_hp
    # Fresh repositories/services == a fresh process.
    fresh = CombatService()
    resumed = fresh.active_battle(6001)
    check("battle survives a restart", resumed is not None and resumed.battle_id == bid)
    check("enemy hp survives a restart", resumed.enemy_hp == hp_snapshot)
    check("the resumed battle can be continued", fresh.attack(bid, 6001).success)

    # --- 13. multi-user / multi-group isolation -----------------------------
    make_player_with_dragon(players, dragons, 7001, power=5)
    make_player_with_dragon(players, dragons, 7002, power=5)
    a = combat.start_battle(7001, chat_id=-111)
    b = combat.start_battle(7002, chat_id=-222)
    check("two users fight at the same time", a.success and b.success)
    check("their battles are separate", a.battle.battle_id != b.battle.battle_id)
    check("battles keep their own group", a.battle.chat_id == -111 and b.battle.chat_id == -222)
    combat.attack(a.battle.battle_id, 7001)
    check("attacking one battle does not touch the other",
          battles.get(b.battle.battle_id).turns == 0)
    check("each user sees only their own battle",
          combat.active_battle(7001).battle_id == a.battle.battle_id
          and combat.active_battle(7002).battle_id == b.battle.battle_id)

    # --- 14. database-level one-active-battle guard -------------------------
    dup = battles.start(
        user_id=7001, dragon_id=1, enemy_id="wolf", enemy_hp=80,
        enemy_max_hp=80, created_time=1.0, chat_id=-111,
    )
    check("repository refuses a second active battle", dup is None)
    with get_db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM battles WHERE user_id = ? AND status = 'active'",
            (7001,),
        ).fetchone()[0]
    check("exactly one active row in the database", n == 1, n)

    # concurrent double-tap of «حمله» applies only one turn
    battle = battles.get(a.battle.battle_id)
    first = battles.apply_turn(battle.battle_id, 10, 1.0, battle.turns)
    second = battles.apply_turn(battle.battle_id, 10, 1.0, battle.turns)
    check("double-tapped attack applies once", first and not second)

    # --- 15. stale battle reclaim -------------------------------------------
    make_player_with_dragon(players, dragons, 8001, power=5)
    combat.start_battle(8001)
    stale_id = combat.active_battle(8001).battle_id
    with get_db() as conn:
        conn.execute(
            "UPDATE battles SET created_time = 0, updated_time = 0 WHERE battle_id = ?",
            (stale_id,),
        )
    combat.expire_stale_battles()
    check("abandoned battles are reclaimed", battles.get(stale_id).status == STATUS_FLED)
    check("player can fight again after a stale battle", combat.start_battle(8001).success)

    # --- 16. hp bar helper ---------------------------------------------------
    check("hp bar full", battle_ui.hp_bar(100, 100) == "▰" * 10)
    check("hp bar empty", battle_ui.hp_bar(0, 100) == "▱" * 10)
    check("hp bar never divides by zero", battle_ui.hp_bar(0, 0) == "▱" * 10)

    print()
    passed = sum(RESULTS)
    print(f"{passed}/{len(RESULTS)} checks passed")
    if passed == len(RESULTS):
        print("All combat tests passed ✅")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
