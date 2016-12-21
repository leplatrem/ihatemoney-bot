# coding: UTF-8
import sys
import asyncio
from collections import defaultdict
from decimal import Decimal

import peinard
import telepot
from telepot.aio.delegate import per_chat_id, create_open, pave_event_space


class Store(object):
    def __init__(self):
        self.accounts = defaultdict(defaultdict(0))

    def save(self):
        with open("accounts.json", "w") as f:
            json.write(f, self.accounts)

    def load(self):
        try:
            with open("accounts.json") as f:
                imported = json.load(f)
            self.accounts.update(imported)
        except IOError:
            pass

    def track(self, gid, uid, amount):
        group_accounts = self.accounts[gid]
        group_accounts.setdefault(uid, 0)
        nb_others = len(group_accounts) - 1
        for user in group_accounts.keys():
            if user == uid:
                self.accounts[gid][user] += amount
            else:
                self.accounts[gid][user] -= (amount / nb_others)

    def resolve(self, gid):
        if len(self.accounts[gid]) == 1:
            return []
        return peinard.heuristic(self.accounts[gid])


class Accounter(telepot.aio.helper.ChatHandler):
    def __init__(self, seed_tuple, store, **kwargs):
        super(Accounter, self).__init__(seed_tuple, **kwargs)
        self.store = store

    async def on_chat_message(self, msg):
        content_type, chat_type, chat_id = telepot.glance(msg)
        if content_type != 'text':
            # Not a text message.
            return

        uid = msg['from']['username']
        gid = msg['chat']['id']

        try:
            cmd, value, thing = msg['text'].split(' ', 2)
            amount = Decimal(value.strip())
        except:
            message = "Usage: /s 43 cheese"
            await self.sender.sendMessage(message)
            return

        self.store.track(gid, uid, amount)

        result = self.store.resolve(gid)
        for transaction in result:
            message = "{} → {}: {}".format(*transaction)
            await self.sender.sendMessage(message)


TOKEN = sys.argv[1]  # get token from command-line

store = Store()
store.load()

bot = telepot.aio.DelegatorBot(TOKEN, [
    pave_event_space()(per_chat_id(types=['group']), create_open, Accounter, store, timeout=10)
])

loop = asyncio.get_event_loop()
loop.create_task(bot.message_loop())
print('Listening ...')

loop.run_forever()

store.save()
