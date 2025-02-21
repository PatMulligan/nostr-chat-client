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
    }
  },
  methods: {
    sendMessage: async function () { },
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

    sendDirectMesage: async function () {
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
    }
  },
  created: async function () {
    console.log(this.peers)
    await this.getPeers()
    this.getPeersDebounced = _.debounce(this.getPeers, 2000, false)
    if (!this.isSuper && this.peers.length == 0) {
      // TODO: automatically connect to super pubkey from db
      // check public key against super
      console.log("in here?")
      this.addPublicKey("08bbdea9491d3d391d8afc2a7b632e23437630ab0bcd21e64b75857caab40f47")
    }
    console.log(this.peers)
    this.activePublicKey = this.peers[0]?.public_key || ''
  },
  beforeDestroy() {
    // Clean up any timers or subscriptions
    if (this.getPeersDebounced) {
      this.getPeersDebounced.cancel();
    }
  }
})
