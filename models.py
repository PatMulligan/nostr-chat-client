import json
import time
from abc import abstractmethod
from enum import Enum
from typing import Any, List, Optional, Tuple

# TODO: don't think needed
# from lnbits.utils.exchange_rates import btc_price, fiat_amount_as_satoshis
from pydantic import BaseModel

from .helpers import (
    decrypt_message,
    encrypt_message,
    get_shared_secret,
    sign_message_hash,
)
from .nostr.event import NostrEvent

######################################## NOSTR ########################################


class Nostrable:
    @abstractmethod
    def to_nostr_event(self, pubkey: str) -> NostrEvent:
        pass

    @abstractmethod
    def to_nostr_delete_event(self, pubkey: str) -> NostrEvent:
        pass


######################################## MERCHANT ######################################


class NostrAcctProfile(BaseModel):
    name: Optional[str] = None
    about: Optional[str] = None
    picture: Optional[str] = None


class NostrAcctConfig(NostrAcctProfile):
    event_id: Optional[str] = None
    sync_from_nostr = False
    active: bool = False
    restore_in_progress: Optional[bool] = False


class PartialNostrAcct(BaseModel):
    private_key: str
    public_key: str
    config: NostrAcctConfig = NostrAcctConfig()


class NostrAcct(PartialNostrAcct, Nostrable):
    id: str
    time: Optional[int] = 0

    def sign_hash(self, hash_: bytes) -> str:
        return sign_message_hash(self.private_key, hash_)

    def decrypt_message(self, encrypted_message: str, public_key: str) -> str:
        encryption_key = get_shared_secret(self.private_key, public_key)
        return decrypt_message(encrypted_message, encryption_key)

    def encrypt_message(self, clear_text_message: str, public_key: str) -> str:
        encryption_key = get_shared_secret(self.private_key, public_key)
        return encrypt_message(clear_text_message, encryption_key)

    def build_dm_event(self, message: str, to_pubkey: str) -> NostrEvent:
        content = self.encrypt_message(message, to_pubkey)
        event = NostrEvent(
            pubkey=self.public_key,
            created_at=round(time.time()),
            kind=4,
            tags=[["p", to_pubkey]],
            content=content,
        )
        event.id = event.event_id
        event.sig = self.sign_hash(bytes.fromhex(event.id))

        return event

    @classmethod
    def from_row(cls, row: dict) -> "NostrAcct":
        nostracct = cls(**row)
        nostracct.config = NostrAcctConfig(**json.loads(row["meta"]))
        return nostracct

    def to_nostr_event(self, pubkey: str) -> NostrEvent:
        content = {
            "name": self.config.name,
            "about": self.config.about,
            "picture": self.config.picture,
        }
        event = NostrEvent(
            pubkey=pubkey,
            created_at=round(time.time()),
            kind=0,
            tags=[],
            content=json.dumps(content, separators=(",", ":"), ensure_ascii=False),
        )
        event.id = event.event_id

        return event

    def to_nostr_delete_event(self, pubkey: str) -> NostrEvent:
        content = {
            "name": f"{self.config.name} (deleted)",
            "about": "NostrAcct Deleted",
            "picture": "",
        }
        delete_event = NostrEvent(
            pubkey=pubkey,
            created_at=round(time.time()),
            kind=5,
            tags=[],
            content=json.dumps(content, separators=(",", ":"), ensure_ascii=False),
        )
        delete_event.id = delete_event.event_id

        return delete_event


######################################## MESSAGE #######################################


class DirectMessageType(Enum):
    """Various types os direct messages."""

    PLAIN_TEXT = -1


class PartialDirectMessage(BaseModel):
    event_id: str
    event_created_at: int
    message: str
    public_key: str
    type: int = DirectMessageType.PLAIN_TEXT.value
    incoming: bool = False  # Default to outgoing if not specified

    @classmethod
    def parse_message(cls, msg) -> Tuple[DirectMessageType, Optional[Any]]:
        try:
            msg_json = json.loads(msg)
            if "type" in msg_json:
                return DirectMessageType(msg_json["type"]), msg_json

            return DirectMessageType.PLAIN_TEXT, None
        except Exception:
            return DirectMessageType.PLAIN_TEXT, None


class DirectMessage(PartialDirectMessage):
    id: str

    @classmethod
    def from_row(cls, row: dict) -> "DirectMessage":
        return cls(**row)


######################################## CUSTOMERS #####################################


class PeerProfile(BaseModel):
    name: Optional[str] = None
    about: Optional[str] = None


class Peer(BaseModel):
    nostracct_id: str
    public_key: str
    event_created_at: Optional[int] = None
    profile: Optional[PeerProfile] = None
    unread_messages: int = 0

    @classmethod
    def from_row(cls, row: dict) -> "Peer":
        peer = cls(**row)
        peer.profile = (
            PeerProfile(**json.loads(row["meta"])) if "meta" in row else None
        )
        return peer
