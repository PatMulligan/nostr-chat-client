window.app.component('direct-messages', {
  name: 'direct-messages',
  props: ['active-chat-peer', 'nostracct-id', 'adminkey', 'inkey', 'is-super'],
  template: '#direct-messages',
  delimiters: ['${', '}'],
  watch: {
    activeChatPeer: async function (n) {
      this.activePublicKey = n
    },
    activePublicKey: async function (n) {
      await this.getDirectMessages(n)
    }
  },
  computed: {
    messagesAsJson: function () {
      return this.messages.map(m => {
        const dateFrom = moment(m.event_created_at * 1000).fromNow()
        try {
          const message = JSON.parse(m.message)
          return {
            isJson: message.type >= 0,
            dateFrom,
            ...m,
            message
          }
        } catch (error) {
          return {
            isJson: false,
            dateFrom,
            ...m,
            message: m.message
          }
        }
      })
    },
    filteredPeers() {
      if (!this.search) return this.peers
      const searchLower = this.search.toLowerCase()
      return this.peers.filter(peer => {
        const name = (peer.profile.name || '').toLowerCase()
        const pubkey = peer.public_key.toLowerCase()
        return name.includes(searchLower) || pubkey.includes(searchLower)
      })
    },
    isMobile() {
      return this.$q.screen.lt.sm
    },
    showPeerList() {
      return !this.isMobile || (this.isMobile && !this.activePublicKey)
    },
    showChatArea() {
      return !this.isMobile || (this.isMobile && this.activePublicKey)
    }
  },
  data: function () {
    return {
      peers: [],
      unreadMessages: 0,
      activePublicKey: null,
      messages: [],
      newMessage: '',
      showAddPublicKey: false,
      newPublicKey: null,
      showRawMessage: false,
      rawMessage: null,
      search: '',
      adminPubkey: null,
    }
  },
  methods: {
    buildPeerLabel: function (c) {
      let label = `${c.profile.name || 'unknown'} ${c.profile.about || ''}`
      if (c.unread_messages) {
        label += `[new: ${c.unread_messages}]`
      }
      label += `  (${c.public_key.slice(0, 16)}...${c.public_key.slice(
        c.public_key.length - 16
      )}`
      return label
    },
    getDirectMessages: async function (pubkey) {
      if (!pubkey) {
        this.messages = []
        return
      }
      try {
        const { data } = await LNbits.api.request(
          'GET',
          '/nostrchat/api/v1/message/' + pubkey,
          this.inkey
        )
        this.messages = data

        this.focusOnChatBox(this.messages.length - 1)
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    getPeers: async function () {
      try {
        const { data } = await LNbits.api.request(
          'GET',
          '/nostrchat/api/v1/peer',
          this.inkey
        )
        this.peers = data
        this.unreadMessages = data.filter(c => c.unread_messages).length
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    sendDirectMessage: async function () {
      try {
        const { data } = await LNbits.api.request(
          'POST',
          '/nostrchat/api/v1/message',
          this.adminkey,
          {
            message: this.newMessage,
            public_key: this.activePublicKey,
            event_id: crypto.randomUUID(),
            event_created_at: Math.floor(Date.now() / 1000)
          }
        )
        this.messages = this.messages.concat([data])
        this.newMessage = ''
        this.focusOnChatBox(this.messages.length - 1)
        this.$refs.newMessage.focus()
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    addPublicKey: async function (pubkey = null) {
      try {
        const { data } = await LNbits.api.request(
          'POST',
          '/nostrchat/api/v1/peer',
          this.adminkey,
          {
            public_key: String(pubkey || this.newPublicKey),
            nostracct_id: this.nostracctId,
            unread_messages: 0
          }
        )
        this.newPublicKey = null
        this.activePublicKey = data.public_key
        await this.selectActivePeer()
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      } finally {
        this.showAddPublicKey = false
      }
    },
    handleNewMessage: async function (data) {
      if (data.peerPubkey === this.activePublicKey) {
        this.messages.push(data.dm)
        this.focusOnChatBox(this.messages.length - 1)
        // focus back on input box
      }
      this.getPeersDebounced()
    },
    showOrderDetails: function (orderId, eventId) {
      this.$emit('order-selected', { orderId, eventId })
    },
    showClientOrders: function () {
      this.$emit('peer-selected', this.activePublicKey)
    },
    selectActivePeer: async function () {
      await this.getDirectMessages(this.activePublicKey)
      await this.getPeers()
    },
    showMessageRawData: function (index) {
      this.rawMessage = this.messages[index]?.message
      this.showRawMessage = true
    },
    focusOnChatBox: function (index) {
      setTimeout(() => {
        const lastChatBox = document.getElementsByClassName(
          `chat-mesage-index-${index}`
        )
        if (lastChatBox && lastChatBox[0]) {
          lastChatBox[0].scrollIntoView()
        }
      }, 100)
    },
    getAdminPubkey: async function () {
      try {
        const { data } = await LNbits.api.request(
          'GET',
          '/nostrchat/api/v1/admin-pubkey',
          this.inkey
        )
        if (data.pubkey) {
          this.adminPubkey = data.pubkey;
          // For non-super users, ensure they only have the admin as a peer
          if (this.peers.length === 0) {
            // Add admin as peer if no peers exist
            await this.addPublicKey(this.adminPubkey)
          } else if (this.peers.length === 1 && this.peers[0].public_key !== data.pubkey) {
            // If one peer exists but it's not the admin, replace it
            this.peers = []
            await this.addPublicKey(this.adminPubkey)
          } else if (this.peers.length > 1 && !this.peers.some(peer => peer.public_key === data.pubkey)) {
            // If multiple peers exist, clear them and add only admin
            this.peers = []
            await this.addPublicKey(this.adminPubkey)
          }

          // Automatically set active chat to admin
          this.activePublicKey = this.adminPubkey
        }
      } catch (error) {
        console.error('Failed to fetch admin pubkey:', error);
      }
    },
    clearActivePeer() {
      this.activePublicKey = null
      this.messages = []
    }
  },
  mounted: async function () {
    await this.getPeers()
    this.getPeersDebounced = _.debounce(this.getPeers, 2000, false)
    if (!this.isSuper) {
      // Fetch admin pubkey for non-admin users
      await this.getAdminPubkey()
    }
  },
  beforeDestroy() {
    // Clean up any timers or subscriptions
    if (this.getPeersDebounced) {
      this.getPeersDebounced.cancel();
    }
  }
})
