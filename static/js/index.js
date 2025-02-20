const nostr = window.NostrTools

window.app = Vue.createApp({
  el: '#vue',
  mixins: [window.windowMixin],
  data: function () {
    return {
      nostracct: {},
      activeChatPeer: '',
      showKeys: false,
      importKeyDialog: {
        show: false,
        data: {
          privateKey: null
        }
      },
      wsConnection: null
    }
  },
  methods: {
    generateKeys: async function () {
      const privateKey = nostr.generatePrivateKey()
      await this.createNostrAcct(privateKey)
    },
    importKeys: async function () {
      this.importKeyDialog.show = false
      let privateKey = this.importKeyDialog.data.privateKey
      if (!privateKey) {
        return
      }
      try {
        if (privateKey.toLowerCase().startsWith('nsec')) {
          privateKey = nostr.nip19.decode(privateKey).data
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: `${error}`
        })
      }
      await this.createNostrAcct(privateKey)
    },
    showImportKeysDialog: async function () {
      this.importKeyDialog.show = true
    },
    toggleShowKeys: function () {
      this.showKeys = !this.showKeys
    },
    toggleNostrAcctState: async function () {
      const nostracct = await this.getNostrAcct()
      if (!nostracct) {
        this.$q.notify({
          timeout: 5000,
          type: 'warning',
          message: 'Cannot fetch nostracct!'
        })
        return
      }
      const message = nostracct.config.active
        ? 'New orders will not be processed. Are you sure you want to deactivate?'
        : nostracct.config.restore_in_progress
          ? 'Nostr account restore  from nostr in progress. Please wait!! ' +
          'Activating now can lead to duplicate order processing. Click "OK" if you want to activate anyway?'
          : 'Are you sure you want activate this nostr account?'

      LNbits.utils.confirmDialog(message).onOk(async () => {
        await this.toggleNostrAcct()
      })
    },
    // NOTE: Leaving toggle functionality for now
    // in the case it makes sense to handle nostrMarket and other extension chats altogether
    toggleNostrAcct: async function () {
      try {
        const { data } = await LNbits.api.request(
          'PUT',
          `/nostrchat/api/v1/nostracct/${this.nostracct.id}/toggle`,
          this.g.user.wallets[0].adminkey
        )
        const state = data.config.active ? 'activated' : 'disabled'
        this.nostracct = data
        this.$q.notify({
          type: 'positive',
          message: `'NostrAcct ${state}`,
          timeout: 5000
        })
      } catch (error) {
        console.warn(error)
        LNbits.utils.notifyApiError(error)
      }
    },
    handleNostrAcctDeleted: function () {
      this.nostracct = null
      this.activeChatPeer = ''
      this.showKeys = false
    },
    createNostrAcct: async function (privateKey) {
      try {
        const pubkey = nostr.getPublicKey(privateKey)
        const payload = {
          private_key: privateKey,
          public_key: pubkey,
          config: {}
        }
        const { data } = await LNbits.api.request(
          'POST',
          '/nostrchat/api/v1/nostracct',
          this.g.user.wallets[0].adminkey,
          payload
        )
        this.nostracct = data
        this.$q.notify({
          type: 'positive',
          message: 'Nostr Account Created!'
        })
        this.waitForNotifications()
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    getNostrAcct: async function () {
      try {
        const { data } = await LNbits.api.request(
          'GET',
          '/nostrchat/api/v1/nostracct',
          this.g.user.wallets[0].inkey
        )
        this.nostracct = data
        return data
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    // TODO: remove this
    peerSelectedForOrder: function (peerPubkey) {
      this.activeChatPeer = peerPubkey
    },
    // TODO: remove this
    // filterOrdersForPeer: function (peerPubkey) {
    //   this.orderPubkey = peerPubkey
    // },
    waitForNotifications: async function () {
      if (!this.nostracct) return
      try {
        const scheme = location.protocol === 'http:' ? 'ws' : 'wss'
        const port = location.port ? `:${location.port}` : ''
        const wsUrl = `${scheme}://${document.domain}${port}/api/v1/ws/${this.nostracct.id}`
        console.log('Reconnecting to websocket: ', wsUrl)
        this.wsConnection = new WebSocket(wsUrl)
        this.wsConnection.onmessage = async e => {
          const data = JSON.parse(e.data)
          if (data.type === 'dm:-1') {
            await this.$refs.directMessagesRef.handleNewMessage(data)
          }
        }
      } catch (error) {
        this.$q.notify({
          timeout: 5000,
          type: 'warning',
          message: 'Failed to watch for updates',
          caption: `${error}`
        })
      }
    },
    restartNostrConnection: async function () {
      LNbits.utils
        .confirmDialog(
          'Are you sure you want to reconnect to the nostrcient extension?'
        )
        .onOk(async () => {
          try {
            await LNbits.api.request(
              'PUT',
              '/nostrchat/api/v1/restart',
              this.g.user.wallets[0].adminkey
            )
          } catch (error) {
            LNbits.utils.notifyApiError(error)
          }
        })
    }
  },
  created: async function () {
    await this.getNostrAcct()
    setInterval(async () => {
      if (
        !this.wsConnection ||
        this.wsConnection.readyState !== WebSocket.OPEN
      ) {
        await this.waitForNotifications()
      }
    }, 1000)
  }
})
