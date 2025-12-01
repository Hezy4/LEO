"""Persona matrix and mood stores."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Mapping

from leo.db import Database


def _now() -> datetime:
    """Return a naive UTC timestamp matching SQLite CURRENT_TIMESTAMP behavior."""
    return datetime.utcnow()


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return _now()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return _now()


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class PersonaTrait:
    id: int | None
    user_id: str
    name: str
    description: str | None
    coords: dict[str, float]
    importance: float
    plasticity: float
    locked: bool
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class PersonaSettings:
    user_id: str
    personality_axes: dict[str, Any]
    evolution_settings: dict[str, Any]
    mood_axes: dict[str, Any]
    decay_settings: dict[str, Any]
    interaction_effects: dict[str, Any]
    version: int


@dataclass(slots=True)
class MoodState:
    user_id: str
    session_id: str
    values: dict[str, float]
    updated_at: datetime


class PersonaStore:
    """Handles persona matrices (axes, traits, evolution/mood settings)."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def load_matrix(self, user_id: str, matrix: Mapping[str, Any], version: int = 1) -> None:
        """Load a persona matrix payload into settings and trait tables."""

        personality_axes = matrix.get("personality_axes", {})
        traits = matrix.get("traits", [])
        evolution = matrix.get("evolution_settings", {})
        mood_system = matrix.get("mood_system", {})
        mood_axes = mood_system.get("axes", {})
        decay_settings = mood_system.get("decay_settings", {})
        interaction_effects = mood_system.get("interaction_effects", {})

        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, display_name) VALUES (?, ?)",
                (user_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO persona_settings (
                    user_id, personality_axes, evolution_settings, mood_axes, decay_settings,
                    interaction_effects, version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    personality_axes=excluded.personality_axes,
                    evolution_settings=excluded.evolution_settings,
                    mood_axes=excluded.mood_axes,
                    decay_settings=excluded.decay_settings,
                    interaction_effects=excluded.interaction_effects,
                    version=excluded.version,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    json.dumps(personality_axes),
                    json.dumps(evolution),
                    json.dumps(mood_axes),
                    json.dumps(decay_settings),
                    json.dumps(interaction_effects),
                    version,
                ),
            )

            for trait in traits:
                self._upsert_trait(conn, user_id, trait)
            conn.commit()

    def _upsert_trait(self, conn, user_id: str, trait: Mapping[str, Any]) -> None:
        coords = trait.get("coords", {})
        metadata = {k: v for k, v in trait.items() if k not in {"name", "description", "coords", "importance", "plasticity", "locked"}}
        conn.execute(
            """
            INSERT INTO persona_traits (
                user_id, name, description, coords, importance, plasticity, locked, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, name) DO UPDATE SET
                description=excluded.description,
                coords=excluded.coords,
                importance=excluded.importance,
                plasticity=excluded.plasticity,
                locked=excluded.locked,
                metadata=excluded.metadata,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                user_id,
                trait.get("name"),
                trait.get("description"),
                json.dumps(coords),
                float(trait.get("importance", 0.0)),
                float(trait.get("plasticity", 0.0)),
                1 if trait.get("locked") else 0,
                json.dumps(metadata) if metadata else None,
            ),
        )

    def get_settings(self, user_id: str) -> PersonaSettings | None:
        rows = self.db.query(
            """
            SELECT personality_axes, evolution_settings, mood_axes, decay_settings,
                   interaction_effects, version
            FROM persona_settings
            WHERE user_id = ?
            LIMIT 1
            """,
            (user_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return PersonaSettings(
            user_id=user_id,
            personality_axes=json.loads(row["personality_axes"]),
            evolution_settings=json.loads(row["evolution_settings"]),
            mood_axes=json.loads(row["mood_axes"]),
            decay_settings=json.loads(row["decay_settings"]),
            interaction_effects=json.loads(row["interaction_effects"]),
            version=int(row["version"]),
        )

    def list_traits(self, user_id: str) -> list[PersonaTrait]:
        rows = self.db.query(
            """
            SELECT id, user_id, name, description, coords, importance, plasticity, locked, metadata
            FROM persona_traits
            WHERE user_id = ?
            ORDER BY importance DESC, name ASC
            """,
            (user_id,),
        )
        traits: list[PersonaTrait] = []
        for row in rows:
            traits.append(
                PersonaTrait(
                    id=row["id"],
                    user_id=row["user_id"],
                    name=row["name"],
                    description=row["description"],
                    coords=json.loads(row["coords"]),
                    importance=float(row["importance"]),
                    plasticity=float(row["plasticity"]),
                    locked=bool(row["locked"]),
                    metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                )
            )
        return traits

    def record_trait_usage(self, trait_ids: Iterable[int]) -> None:
        now = _now().strftime("%Y-%m-%d %H:%M:%S")
        with self.db.connect() as conn:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_persona_trait_usage_trait_id ON persona_trait_usage(trait_id)"
            )
            for trait_id in trait_ids:
                conn.execute(
                    """
                    INSERT INTO persona_trait_usage (trait_id, usage_count, last_used_at)
                    VALUES (?, 1, ?)
                    ON CONFLICT(trait_id) DO UPDATE SET
                        usage_count = usage_count + 1,
                        last_used_at = excluded.last_used_at
                    """,
                    (trait_id, now),
                )
            conn.commit()

    def update_importance(
        self,
        updates: Mapping[int, float],
    ) -> None:
        """Batch update importance by trait_id."""

        with self.db.connect() as conn:
            for trait_id, importance in updates.items():
                conn.execute(
                    """
                    UPDATE persona_traits
                    SET importance = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (float(importance), trait_id),
                )
            conn.commit()


class MoodStore:
    """Tracks per-user (and optional per-session) mood with decay toward baseline."""

    def __init__(self, db: Database | None = None, persona_store: PersonaStore | None = None) -> None:
        self.db = db or Database()
        self.persona_store = persona_store or PersonaStore(self.db)

    def get_mood(self, user_id: str, session_id: str = "") -> MoodState:
        row = self._get_row(user_id, session_id)
        settings = self.persona_store.get_settings(user_id)
        decay_config = settings.decay_settings if settings else {}
        values = json.loads(row["mood_values"]) if row else {}
        updated_at = _parse_timestamp(row["updated_at"] if row else None)
        decayed_values = self._apply_decay(values, updated_at, decay_config)
        return MoodState(user_id=user_id, session_id=session_id, values=decayed_values, updated_at=_now())

    def set_mood(self, user_id: str, values: Mapping[str, float], session_id: str = "") -> MoodState:
        clamped = {axis: _clamp(val) for axis, val in values.items()}
        self._persist(user_id, session_id, clamped)
        return MoodState(user_id=user_id, session_id=session_id, values=clamped, updated_at=_now())

    def reset_mood(self, user_id: str, session_id: str = "") -> MoodState:
        settings = self.persona_store.get_settings(user_id)
        decay_config = settings.decay_settings if settings else {}
        floors = decay_config.get("floor_values", {}) if isinstance(decay_config, dict) else {}
        zeroed = {axis: float(floors.get(axis, 0.0)) for axis in (settings.mood_axes or {})} if settings else {}
        self._persist(user_id, session_id, zeroed)
        return MoodState(user_id=user_id, session_id=session_id, values=zeroed, updated_at=_now())

    def apply_interaction_effect(self, user_id: str, effect_name: str, session_id: str = "") -> MoodState:
        settings = self.persona_store.get_settings(user_id)
        if not settings:
            return self.get_mood(user_id, session_id)

        decay_config = settings.decay_settings or {}
        floors = decay_config.get("floor_values", {}) if isinstance(decay_config, dict) else {}
        effects = settings.interaction_effects or {}
        effect_delta = effects.get(effect_name, {})

        current_state = self.get_mood(user_id, session_id)
        new_values: Dict[str, float] = {}
        axes = set(current_state.values.keys()) | set(effect_delta.keys())
        for axis in axes:
            base = current_state.values.get(axis, 0.0)
            delta = effect_delta.get(axis, 0.0)
            updated = _clamp(base + delta)
            floor = float(floors.get(axis, 0.0))
            updated = max(floor, updated)
            new_values[axis] = updated

        self._persist(user_id, session_id, new_values)
        return MoodState(user_id=user_id, session_id=session_id, values=new_values, updated_at=_now())

    def _apply_decay(
        self,
        values: Mapping[str, float],
        updated_at: datetime,
        decay_config: Mapping[str, Any],
    ) -> dict[str, float]:
        if not decay_config:
            return dict(values)

        horizon_hours = float(decay_config.get("horizon_hours", 24))
        floors = decay_config.get("floor_values", {}) if isinstance(decay_config, dict) else {}

        elapsed_hours = max(0.0, (_now() - updated_at).total_seconds() / 3600.0)
        if horizon_hours <= 0:
            factor = 0.0
        else:
            factor = max(0.0, 1.0 - (elapsed_hours / horizon_hours))

        decayed: dict[str, float] = {}
        for axis, value in values.items():
            floor = float(floors.get(axis, 0.0))
            decayed_value = floor + (value - floor) * factor
            decayed[axis] = _clamp(decayed_value)
        # Ensure axes with floors but no existing value still return floor.
        for axis, floor_val in floors.items():
            decayed.setdefault(axis, float(floor_val))
        return decayed

    def _persist(self, user_id: str, session_id: str, values: Mapping[str, float]) -> None:
        payload = json.dumps(values)
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO persona_mood_state (user_id, session_id, mood_values, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, session_id) DO UPDATE SET
                    mood_values=excluded.mood_values,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (user_id, session_id, payload),
            )
            conn.commit()

    def _get_row(self, user_id: str, session_id: str) -> Any:
        rows = self.db.query(
            """
            SELECT mood_values, updated_at
            FROM persona_mood_state
            WHERE user_id = ? AND session_id = ?
            LIMIT 1
            """,
            (user_id, session_id),
        )
        return rows[0] if rows else None


__all__ = ["PersonaStore", "PersonaTrait", "PersonaSettings", "MoodStore", "MoodState"]
