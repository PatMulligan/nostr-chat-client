import json
from http import HTTPStatus
from typing import List, Optional
import time

from fastapi import Depends, WebSocket
from fastapi.exceptions import HTTPException
from lnbits.core.services import websocket_updater
from lnbits.decorators import (
    WalletTypeInfo,
    require_admin_key,
    require_invoice_key,
)
# TODO: remove pretty sure not needed
# from lnbits.utils.exchange_rates import currencies
from loguru import logger

from . import nostr_client, nostrchat_ext
from .crud import (
    create_peer,
    create_direct_message,
    create_nostracct,
    delete_nostracct,
    delete_nostracct_direct_messages,
    get_peer,
    get_peers,
    get_direct_messages,
    get_last_direct_messages_time,
    get_nostracct_by_pubkey,
    get_nostracct_for_user,
    touch_nostracct,
    update_peer_no_unread_messages,
    update_nostracct,
)
from .helpers import normalize_public_key
from .models import (
    Peer,
    DirectMessage,
    NostrAcct,
    PartialDirectMessage,
    PartialNostrAcct,
)
from .services import (
    resubscribe_to_all_nostraccts,
    subscribe_to_all_nostraccts,
    update_nostracct_to_nostr,
)

######################################## MERCHANT ######################################


@nostrchat_ext.post("/api/v1/nostracct")
async def api_create_nostracct(
    data: PartialNostrAcct,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> NostrAcct:

    try:
        nostracct = await get_nostracct_by_pubkey(data.public_key)
        assert nostracct is None, "A nostracct already uses this public key"

        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct is None, "A nostracct already exists for this user"

        nostracct = await create_nostracct(wallet.wallet.user, data)

        await resubscribe_to_all_nostraccts()

        await nostr_client.nostracct_temp_subscription(data.public_key)

        return nostracct
    except AssertionError as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot create nostracct",
        ) from ex


@nostrchat_ext.get("/api/v1/nostracct")
async def api_get_nostracct(
    wallet: WalletTypeInfo = Depends(require_invoice_key),
) -> Optional[NostrAcct]:

    try:
        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        if not nostracct:
            return None

        nostracct = await touch_nostracct(wallet.wallet.user, nostracct.id)
        assert nostracct
        last_dm_time = await get_last_direct_messages_time(nostracct.id)
        assert nostracct.time
        nostracct.config.restore_in_progress = (nostracct.time - last_dm_time) < 30

        return nostracct
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot get nostracct",
        ) from ex


@nostrchat_ext.delete("/api/v1/nostracct/{nostracct_id}")
async def api_delete_nostracct(
    nostracct_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):

    try:
        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct, "NostrAcct cannot be found"
        assert nostracct.id == nostracct_id, "Wrong nostracct ID"

        await nostr_client.unsubscribe_nostraccts()

        await delete_nostracct_direct_messages(nostracct.id)
        await delete_nostracct(nostracct.id)

    except AssertionError as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot get nostracct",
        ) from ex
    finally:
        await subscribe_to_all_nostraccts()


@nostrchat_ext.put("/api/v1/nostracct/{nostracct_id}/nostr")
async def api_republish_nostracct(
    nostracct_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    try:
        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct, "NostrAcct cannot be found"
        assert nostracct.id == nostracct_id, "Wrong nostracct ID"

        nostracct = await update_nostracct_to_nostr(nostracct)
        await update_nostracct(wallet.wallet.user, nostracct.id, nostracct.config)

    except AssertionError as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot republish to nostr",
        ) from ex


@nostrchat_ext.get("/api/v1/nostracct/{nostracct_id}/nostr")
async def api_refresh_nostracct(
    nostracct_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    try:
        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct, "NostrAcct cannot be found"
        assert nostracct.id == nostracct_id, "Wrong nostracct ID"

        await nostr_client.nostracct_temp_subscription(nostracct.public_key)

    except AssertionError as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot refresh from nostr",
        ) from ex


@nostrchat_ext.put("/api/v1/nostracct/{nostracct_id}/toggle")
async def api_toggle_nostracct(
    nostracct_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> NostrAcct:
    try:
        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct, "NostrAcct cannot be found"
        assert nostracct.id == nostracct_id, "Wrong nostracct ID"

        nostracct.config.active = not nostracct.config.active
        await update_nostracct(wallet.wallet.user, nostracct.id, nostracct.config)

        return nostracct
    except AssertionError as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot get nostracct",
        ) from ex


@nostrchat_ext.delete("/api/v1/nostracct/{nostracct_id}/nostr")
async def api_delete_nostracct_on_nostr(
    nostracct_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    try:
        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct, "NostrAcct cannot be found"
        assert nostracct.id == nostracct_id, "Wrong nostracct ID"

        nostracct = await update_nostracct_to_nostr(nostracct, True)
        await update_nostracct(wallet.wallet.user, nostracct.id, nostracct.config)

    except AssertionError as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot get nostracct",
        ) from ex


######################################## DIRECT MESSAGES ###############################


@nostrchat_ext.get("/api/v1/message/{public_key}")
async def api_get_messages(
    public_key: str, wallet: WalletTypeInfo = Depends(require_invoice_key)
) -> List[DirectMessage]:
    try:
        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct, "NostrAcct cannot be found"

        messages = await get_direct_messages(nostracct.id, public_key)
        await update_peer_no_unread_messages(nostracct.id, public_key)
        return messages
    except AssertionError as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot get direct message",
        ) from ex


@nostrchat_ext.post("/api/v1/message")
async def api_create_message(
    data: PartialDirectMessage, wallet: WalletTypeInfo = Depends(require_admin_key)
) -> DirectMessage:
    try:
        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct, "NostrAcct cannot be found"

        dm_event = nostracct.build_dm_event(data.message, data.public_key)
        data.event_id = dm_event.id
        data.event_created_at = dm_event.created_at

        dm = await create_direct_message(nostracct.id, data)
        await nostr_client.publish_nostr_event(dm_event)

        return dm
    except AssertionError as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot create message",
        ) from ex


######################################## CUSTOMERS #####################################


@nostrchat_ext.get("/api/v1/peer")
async def api_get_peers(
    wallet: WalletTypeInfo = Depends(require_invoice_key),
) -> List[Peer]:
    try:
        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct, "NostrAcct cannot be found"
        return await get_peers(nostracct.id)

    except AssertionError as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot create message",
        ) from ex


@nostrchat_ext.post("/api/v1/peer")
async def api_create_peer(
    data: Peer,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> Peer:

    try:
        pubkey = normalize_public_key(data.public_key)

        nostracct = await get_nostracct_for_user(wallet.wallet.user)
        assert nostracct, "A nostracct does not exists for this user"
        assert nostracct.id == data.nostracct_id, "Invalid nostracct id for user"

        existing_peer = await get_peer(nostracct.id, pubkey)
        assert existing_peer is None, "This public key already exists"

        peer = await create_peer(
            nostracct.id, Peer(nostracct_id=nostracct.id, public_key=pubkey)
        )

        await nostr_client.user_profile_temp_subscribe(pubkey)

        return peer
    except (ValueError, AssertionError) as ex:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(ex),
        ) from ex
    except Exception as ex:
        logger.warning(ex)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Cannot create peer",
        ) from ex


######################################## OTHER ########################################


# NOTE: keep for later integrations
# @nostrchat_ext.get("/api/v1/currencies")
# async def api_list_currencies_available():
#     return list(currencies.keys())


@nostrchat_ext.put("/api/v1/restart")
async def restart_nostr_client(wallet: WalletTypeInfo = Depends(require_admin_key)):
    try:
        await nostr_client.restart()
    except Exception as ex:
        logger.warning(ex)

