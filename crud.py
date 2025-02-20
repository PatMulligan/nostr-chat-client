import json
from typing import List, Optional, Tuple

from lnbits.helpers import urlsafe_short_hash

from . import db
from .models import (
    Peer,
    PeerProfile,
    DirectMessage,
    NostrAcct,
    NostrAcctConfig,
    PartialDirectMessage,
    PartialNostrAcct,
)

######################################## MERCHANT ######################################


async def create_nostracct(user_id: str, m: PartialNostrAcct) -> NostrAcct:
    nostracct_id = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO nostrchat.nostraccts
               (user_id, id, private_key, public_key, meta)
        VALUES (:user_id, :id, :private_key, :public_key, :meta)
        """,
        {
            "user_id": user_id,
            "id": nostracct_id,
            "private_key": m.private_key,
            "public_key": m.public_key,
            "meta": json.dumps(dict(m.config)),
        },
    )
    nostracct = await get_nostracct(user_id, nostracct_id)
    assert nostracct, "Created nostracct cannot be retrieved"
    return nostracct


async def update_nostracct(
    user_id: str, nostracct_id: str, config: NostrAcctConfig
) -> Optional[NostrAcct]:
    await db.execute(
        f"""
            UPDATE nostrchat.nostraccts SET meta = :meta, time = {db.timestamp_now}
            WHERE id = :id AND user_id = :user_id
        """,
        {"meta": json.dumps(config.dict()), "id": nostracct_id, "user_id": user_id},
    )
    return await get_nostracct(user_id, nostracct_id)


async def touch_nostracct(user_id: str, nostracct_id: str) -> Optional[NostrAcct]:
    await db.execute(
        f"""
            UPDATE nostrchat.nostraccts SET time = {db.timestamp_now}
            WHERE id = :id AND user_id = :user_id
        """,
        {"id": nostracct_id, "user_id": user_id},
    )
    return await get_nostracct(user_id, nostracct_id)


async def get_nostracct(user_id: str, nostracct_id: str) -> Optional[NostrAcct]:
    row: dict = await db.fetchone(
        """SELECT * FROM nostrchat.nostraccts WHERE user_id = :user_id AND id = :id""",
        {
            "user_id": user_id,
            "id": nostracct_id,
        },
    )

    return NostrAcct.from_row(row) if row else None


async def get_nostracct_by_pubkey(public_key: str) -> Optional[NostrAcct]:
    row: dict = await db.fetchone(
        """SELECT * FROM nostrchat.nostraccts WHERE public_key = :public_key""",
        {"public_key": public_key},
    )

    return NostrAcct.from_row(row) if row else None


async def get_nostraccts_ids_with_pubkeys() -> List[Tuple[str, str]]:
    rows: list[dict] = await db.fetchall(
        """SELECT id, public_key FROM nostrchat.nostraccts""",
    )

    return [(row["id"], row["public_key"]) for row in rows]


async def get_nostracct_for_user(user_id: str) -> Optional[NostrAcct]:
    row: dict = await db.fetchone(
        """SELECT * FROM nostrchat.nostraccts WHERE user_id = :user_id """,
        {"user_id": user_id},
    )

    return NostrAcct.from_row(row) if row else None


async def delete_nostracct(nostracct_id: str) -> None:
    await db.execute(
        "DELETE FROM nostrchat.nostraccts WHERE id = :id",
        {
            "id": nostracct_id,
        },
    )


######################################## MESSAGES ######################################


async def create_direct_message(
    nostracct_id: str, dm: PartialDirectMessage
) -> DirectMessage:
    dm_id = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO nostrchat.direct_messages
        (
            nostracct_id, id, event_id, event_created_at,
            message, public_key, type, incoming
        )
        VALUES
            (
            :nostracct_id, :id, :event_id, :event_created_at,
            :message, :public_key, :type, :incoming
            )
        ON CONFLICT(event_id) DO NOTHING
        """,
        {
            "nostracct_id": nostracct_id,
            "id": dm_id,
            "event_id": dm.event_id,
            "event_created_at": dm.event_created_at,
            "message": dm.message,
            "public_key": dm.public_key,
            "type": dm.type,
            "incoming": dm.incoming,
        },
    )
    if dm.event_id:
        msg = await get_direct_message_by_event_id(nostracct_id, dm.event_id)
    else:
        msg = await get_direct_message(nostracct_id, dm_id)
    assert msg, "Newly created dm couldn't be retrieved"
    return msg


async def get_direct_message(nostracct_id: str, dm_id: str) -> Optional[DirectMessage]:
    row: dict = await db.fetchone(
        """
            SELECT * FROM nostrchat.direct_messages
            WHERE nostracct_id = :nostracct_id AND id = :id
        """,
        {
            "nostracct_id": nostracct_id,
            "id": dm_id,
        },
    )
    return DirectMessage.from_row(row) if row else None


async def get_direct_message_by_event_id(
    nostracct_id: str, event_id: str
) -> Optional[DirectMessage]:
    row: dict = await db.fetchone(
        """
        SELECT * FROM nostrchat.direct_messages
        WHERE nostracct_id = :nostracct_id AND event_id = :event_id
        """,
        {
            "nostracct_id": nostracct_id,
            "event_id": event_id,
        },
    )
    return DirectMessage.from_row(row) if row else None


async def get_direct_messages(nostracct_id: str, public_key: str) -> List[DirectMessage]:
    rows: list[dict] = await db.fetchall(
        """
        SELECT * FROM nostrchat.direct_messages
        WHERE nostracct_id = :nostracct_id AND public_key = :public_key
        ORDER BY event_created_at
        """,
        {"nostracct_id": nostracct_id, "public_key": public_key},
    )
    return [DirectMessage.from_row(row) for row in rows]


# TODO: remove
async def get_orders_from_direct_messages(nostracct_id: str) -> List[DirectMessage]:
    rows: list[dict] = await db.fetchall(
        """
        SELECT * FROM nostrchat.direct_messages
        WHERE nostracct_id = :nostracct_id AND type >= 0 ORDER BY event_created_at, type
        """,
        {"nostracct_id": nostracct_id},
    )
    return [DirectMessage.from_row(row) for row in rows]


async def get_last_direct_messages_time(nostracct_id: str) -> int:
    row: dict = await db.fetchone(
        """
            SELECT time FROM nostrchat.direct_messages
            WHERE nostracct_id = :nostracct_id ORDER BY time DESC LIMIT 1
        """,
        {"nostracct_id": nostracct_id},
    )
    return row["time"] if row else 0


async def get_last_direct_messages_created_at() -> int:
    row: dict = await db.fetchone(
        """
            SELECT event_created_at FROM nostrchat.direct_messages
            ORDER BY event_created_at DESC LIMIT 1
        """,
        {},
    )
    return row["event_created_at"] if row else 0


async def delete_nostracct_direct_messages(nostracct_id: str) -> None:
    await db.execute(
        "DELETE FROM nostrchat.direct_messages WHERE nostracct_id = :nostracct_id",
        {"nostracct_id": nostracct_id},
    )


######################################## PEERS #####################################


async def create_peer(nostracct_id: str, data: Peer) -> Peer:
    await db.execute(
        """
        INSERT INTO nostrchat.peers (nostracct_id, public_key, meta)
        VALUES (:nostracct_id, :public_key, :meta)
        """,
        {
            "nostracct_id": nostracct_id,
            "public_key": data.public_key,
            "meta": json.dumps(data.profile) if data.profile else "{}",
        },
    )

    peer = await get_peer(nostracct_id, data.public_key)
    assert peer, "Newly created peer couldn't be retrieved"
    return peer


async def get_peer(nostracct_id: str, public_key: str) -> Optional[Peer]:
    row: dict = await db.fetchone(
        """
            SELECT * FROM nostrchat.peers
            WHERE nostracct_id = :nostracct_id AND public_key = :public_key
        """,
        {
            "nostracct_id": nostracct_id,
            "public_key": public_key,
        },
    )
    return Peer.from_row(row) if row else None


async def get_peers(nostracct_id: str) -> List[Peer]:
    rows: list[dict] = await db.fetchall(
        "SELECT * FROM nostrchat.peers WHERE nostracct_id = :nostracct_id",
        {"nostracct_id": nostracct_id},
    )
    return [Peer.from_row(row) for row in rows]


async def get_all_unique_peers() -> List[Peer]:
    q = """
            SELECT public_key, MAX(nostracct_id) as nostracct_id, MAX(event_created_at)
            FROM nostrchat.peers
            GROUP BY public_key
        """
    rows: list[dict] = await db.fetchall(q)
    return [Peer.from_row(row) for row in rows]


async def update_peer_profile(
    public_key: str, event_created_at: int, profile: PeerProfile
):
    await db.execute(
        """
        UPDATE nostrchat.peers
        SET event_created_at = :event_created_at, meta = :meta
        WHERE public_key = :public_key
        """,
        {
            "event_created_at": event_created_at,
            "meta": json.dumps(profile.dict()),
            "public_key": public_key,
        },
    )


async def increment_peer_unread_messages(nostracct_id: str, public_key: str):
    await db.execute(
        """
        UPDATE nostrchat.peers
        SET unread_messages = unread_messages + 1
        WHERE nostracct_id = :nostracct_id AND public_key = :public_key
        """,
        {
            "nostracct_id": nostracct_id,
            "public_key": public_key,
        },
    )


# ??? two nostraccts
async def update_peer_no_unread_messages(nostracct_id: str, public_key: str):
    await db.execute(
        """
        UPDATE nostrchat.peers
        SET unread_messages = 0
        WHERE nostracct_id = :nostracct_id AND public_key = :public_key
        """,
        {
            "nostracct_id": nostracct_id,
            "public_key": public_key,
        },
    )
