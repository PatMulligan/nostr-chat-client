async def m001_initial(db):
    """
    Initial nostraccts table.
    """
    await db.execute(
        """
        CREATE TABLE nostrchat.nostraccts (
            user_id TEXT NOT NULL,
            id TEXT PRIMARY KEY,
            private_key TEXT NOT NULL,
            public_key TEXT NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}',
            time TIMESTAMP
        );
        """
    )

    """
    Initial chat messages table.
    """
    await db.execute(
        f"""
        CREATE TABLE nostrchat.direct_messages (
            nostracct_id TEXT NOT NULL,
            id TEXT PRIMARY KEY,
            event_id TEXT,
            event_created_at INTEGER NOT NULL,
            message TEXT NOT NULL,
            public_key TEXT NOT NULL,
            incoming BOOLEAN NOT NULL DEFAULT false,
            time TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
            type INTEGER NOT NULL DEFAULT -1,
            UNIQUE(event_id)
        );
        """
    )

    if db.type != "SQLITE":
        """
        Create indexes for message fetching
        """
        await db.execute(
            """
            CREATE INDEX idx_messages_timestamp
            ON nostrchat.direct_messages (time DESC)
            """
        )
        await db.execute(
            "CREATE INDEX idx_event_id ON nostrchat.direct_messages (event_id)"
        )

    """
    Initial peers table.
    """
    await db.execute(
        """
        CREATE TABLE nostrchat.peers (
            nostracct_id TEXT NOT NULL,
            public_key TEXT NOT NULL,
            event_created_at INTEGER,
            unread_messages INTEGER NOT NULL DEFAULT 1,
            meta TEXT NOT NULL DEFAULT '{}'
        );
        """
    )

async def m002_admin_config(db):
    """
    Create admin_config table to store admin's public key
    """
    await db.execute(
        """
        CREATE TABLE nostrchat.admin_config (
            id TEXT PRIMARY KEY,
            admin_pubkey TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

async def m003_admin_config_update(db):
    """
    Update admin_config table to make nostracct_id NOT NULL
    """
    # First create new table with desired schema
    await db.execute(
        """
        CREATE TABLE nostrchat.admin_config_new (
            nostracct_id TEXT NOT NULL PRIMARY KEY,
            admin_pubkey TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # Drop old table
    await db.execute(
        """
        DROP TABLE nostrchat.admin_config;
        """
    )

    # Rename new table to original name
    await db.execute(
        """
        ALTER TABLE nostrchat.admin_config_new RENAME TO admin_config;
        """
    )

