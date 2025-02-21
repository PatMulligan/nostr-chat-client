import asyncio
import json
from typing import List, Optional, Tuple

from lnbits.bolt11 import decode
from lnbits.core.crud import get_wallet
from lnbits.core.services import create_invoice, websocket_updater
from loguru import logger

from . import nostr_client
from .crud import (
    PeerProfile,
    create_peer,
    create_direct_message,
    get_peer,
    get_last_direct_messages_created_at,
    get_nostracct_by_pubkey,
    get_nostraccts_ids_with_pubkeys,
    increment_peer_unread_messages,
    update_peer_profile,
)
from .models import (
    Peer,
    DirectMessage,
    DirectMessageType,
    NostrAcct,
    Nostrable,
    PartialDirectMessage,
)
from .nostr.event import NostrEvent

async def update_nostracct_to_nostr(
    nostracct: NostrAcct, delete_nostracct=False
) -> NostrAcct:
    event: Optional[NostrEvent] = None
    if delete_nostracct:
        # nostracct profile updates not supported yet
        event = await sign_and_send_to_nostr(nostracct, nostracct, delete_nostracct)
    assert event
    nostracct.config.event_id = event.id
    return nostracct


async def sign_and_send_to_nostr(
    nostracct: NostrAcct, n: Nostrable, delete=False
) -> NostrEvent:
    event = (
        n.to_nostr_delete_event(nostracct.public_key)
        if delete
        else n.to_nostr_event(nostracct.public_key)
    )
    event.sig = nostracct.sign_hash(bytes.fromhex(event.id))
    await nostr_client.publish_nostr_event(event)

    return event


async def send_dm(
    nostracct: NostrAcct,
    other_pubkey: str,
    type_: int,
    dm_content: str,
    event_id: Optional[str] = None,
    event_created_at: Optional[int] = None,
):
    logger.debug(f"Sending DM to {other_pubkey}")
    # If event_id and created_at not provided, create new event
    if not event_id or not event_created_at:
        dm_event = nostracct.build_dm_event(dm_content, other_pubkey)
        event_id = dm_event.id
        event_created_at = dm_event.created_at
    else:
        # Use provided values for local message
        dm_event = NostrEvent(
            id=event_id,
            pubkey=nostracct.public_key,
            created_at=event_created_at,
            kind=4,
            tags=[["p", other_pubkey]],
            content=nostracct.encrypt_message(dm_content, other_pubkey)
        )
        dm_event.sig = nostracct.sign_hash(bytes.fromhex(dm_event.id))

    dm = PartialDirectMessage(
        event_id=event_id,
        event_created_at=event_created_at,
        message=dm_content,
        public_key=other_pubkey,
        type=type_,
    )
    dm_reply = await create_direct_message(nostracct.id, dm)
    logger.debug(f"Created DM in database with id {dm_reply.id}")

    await nostr_client.publish_nostr_event(dm_event)
    logger.debug("Published event to nostr relay")

    await websocket_updater(
        nostracct.id,
        json.dumps(
            {
                "type": f"dm:{dm.type}",
                "peerPubkey": other_pubkey,
                "dm": dm_reply.dict(),
            }
        ),
    )


async def process_nostr_message(msg: str):
    try:
        type_, *rest = json.loads(msg)

        if type_.upper() == "EVENT":
            _, event = rest
            event = NostrEvent(**event)
            if event.kind == 0:
                await _handle_peer_profile_update(event)
            elif event.kind == 4:
                await _handle_nip04_message(event)
            return

    except Exception as ex:
        logger.debug(ex)

async def _handle_nip04_message(event: NostrEvent):
    p_tags = event.tag_values("p")
    if not p_tags:
        logger.warning(f"NIP04 event has no 'p' tag: '{event.id}'")
        return

    sender = await get_nostracct_by_pubkey(event.pubkey)
    recipient = await get_nostracct_by_pubkey(p_tags[0])

    if not sender and not recipient:
        logger.debug(f"Neither sender nor recipient are in our database for event: {event.id}")
        return

    try:
        if sender:
            clear_text_msg = sender.decrypt_message(event.content, p_tags[0])
            dm = await _handle_outgoing_dms(event, sender, clear_text_msg)
            
            if recipient:
                # Create a copy of the message for the recipient with incoming=True
                incoming_dm = PartialDirectMessage(
                    event_id=f"{event.id}_incoming",  # Make unique event_id for recipient's copy
                    event_created_at=event.created_at,
                    message=clear_text_msg,
                    public_key=event.pubkey,  # Set to sender's pubkey for recipient
                    type=dm.type,
                    incoming=True  # Mark as incoming for recipient
                )
                try:
                    recipient_dm = await create_direct_message(recipient.id, incoming_dm)
                    
                    # Update unread count and handle peer creation
                    peer = await get_peer(recipient.id, event.pubkey)
                    if not peer:
                        await _handle_new_peer(event, recipient)
                    await increment_peer_unread_messages(recipient.id, event.pubkey)
                    
                    # Notify recipient with the incoming message
                    await websocket_updater(
                        recipient.id,
                        json.dumps({
                            "type": f"dm:{dm.type}",
                            "peerPubkey": event.pubkey,
                            "dm": recipient_dm.dict(),
                        })
                    )
                except Exception as ex:
                    logger.warning(f"Error creating recipient copy of message: {str(ex)}")
                
        # Handle as incoming message only if we have recipient but not sender
        elif recipient:
            clear_text_msg = recipient.decrypt_message(event.content, event.pubkey)
            await _handle_incoming_dms(event, recipient, clear_text_msg)

    except Exception as ex:
        logger.warning(f"Error processing NIP04 message {event.id}: {str(ex)}")


async def _handle_incoming_dms(
    event: NostrEvent, nostracct: NostrAcct, clear_text_msg: str
):
    peer = await get_peer(nostracct.id, event.pubkey)
    if not peer:
        await _handle_new_peer(event, nostracct)
    else:
        await increment_peer_unread_messages(nostracct.id, event.pubkey)

    dm_type, json_data = PartialDirectMessage.parse_message(clear_text_msg)
    new_dm = await _persist_dm(
        nostracct.id,
        dm_type.value,
        event.pubkey,
        event.id,
        event.created_at,
        clear_text_msg,
    )

    # TODO: comment out for now
    # if json_data:
    #     reply_type, dm_reply = await _handle_incoming_structured_dm(
    #         nostracct, new_dm, json_data
    #     )
    #     if dm_reply:
    #         await reply_to_structured_dm(
    #             nostracct, event.pubkey, reply_type.value, dm_reply
    #         )


async def _handle_outgoing_dms(
    event: NostrEvent, nostracct: NostrAcct, clear_text_msg: str
) -> DirectMessage:
    sent_to = event.tag_values("p")
    type_, _ = PartialDirectMessage.parse_message(clear_text_msg)
    if len(sent_to) != 0:
        dm = PartialDirectMessage(
            event_id=event.id,
            event_created_at=event.created_at,
            message=clear_text_msg,
            public_key=sent_to[0],
            type=type_.value,
        )
        return await create_direct_message(nostracct.id, dm)
    raise ValueError("No recipient in p tags")


# TODO: comment out for now
# async def _handle_incoming_structured_dm(
#     nostracct: NostrAcct, dm: DirectMessage, json_data: dict
# ) -> Tuple[DirectMessageType, Optional[str]]:
#     try:
#         if dm.type == DirectMessageType.CUSTOMER_ORDER.value and nostracct.config.active:
#             json_resp = await _handle_new_order(
#                 nostracct.id, nostracct.public_key, dm, json_data
#             )
#
#             return DirectMessageType.PAYMENT_REQUEST, json_resp
#
#     except Exception as ex:
#         logger.warning(ex)
#
#     return DirectMessageType.PLAIN_TEXT, None


async def _persist_dm(
    nostracct_id: str,
    dm_type: int,
    from_pubkey: str,
    event_id: str,
    event_created_at: int,
    msg: str,
) -> DirectMessage:
    dm = PartialDirectMessage(
        event_id=event_id,
        event_created_at=event_created_at,
        message=msg,
        public_key=from_pubkey,
        incoming=True,
        type=dm_type,
    )
    new_dm = await create_direct_message(nostracct_id, dm)

    await websocket_updater(
        nostracct_id,
        json.dumps(
            {
                "type": f"dm:{dm_type}",
                "peerPubkey": from_pubkey,
                "dm": new_dm.dict(),
            }
        ),
    )
    return new_dm


async def reply_to_structured_dm(
    nostracct: NostrAcct, peer_pubkey: str, dm_type: int, dm_reply: str
):
    dm_event = nostracct.build_dm_event(dm_reply, peer_pubkey)
    dm = PartialDirectMessage(
        event_id=dm_event.id,
        event_created_at=dm_event.created_at,
        message=dm_reply,
        public_key=peer_pubkey,
        type=dm_type,
    )
    await create_direct_message(nostracct.id, dm)
    await nostr_client.publish_nostr_event(dm_event)

    await websocket_updater(
        nostracct.id,
        json.dumps(
            {"type": f"dm:{dm_type}", "peerPubkey": dm.public_key, "dm": dm.dict()}
        ),
    )

async def resubscribe_to_all_nostraccts():
    await nostr_client.unsubscribe_nostraccts()
    # give some time for the message to propagate
    await asyncio.sleep(1)
    await subscribe_to_all_nostraccts()


async def subscribe_to_all_nostraccts():
    ids = await get_nostraccts_ids_with_pubkeys()
    public_keys = [pk for _, pk in ids]

    last_dm_time = await get_last_direct_messages_created_at()

    await nostr_client.subscribe_nostraccts(
        public_keys, last_dm_time, 0
    )


async def _handle_new_peer(event: NostrEvent, nostracct: NostrAcct):
    await create_peer(
        nostracct.id, Peer(nostracct_id=nostracct.id, public_key=event.pubkey)
    )
    await nostr_client.user_profile_temp_subscribe(event.pubkey)


async def _handle_peer_profile_update(event: NostrEvent):
    try:
        profile = json.loads(event.content)
        await update_peer_profile(
            event.pubkey,
            event.created_at,
            PeerProfile(
                name=profile["name"] if "name" in profile else "",
                about=profile["about"] if "about" in profile else "",
            ),
        )
    except Exception as ex:
        logger.warning(ex)

