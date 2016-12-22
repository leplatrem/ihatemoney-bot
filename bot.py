# coding: UTF-8
import asyncio
import datetime
import json
import re
import sys
from decimal import Decimal

import peinard
import telepot
from telepot.aio.delegate import per_chat_id, create_open, pave_event_space


class Store(object):
    def __init__(self):
        self.accounts = {}

    def save(self):
        with open("accounts.json", "w") as f:
            json.dump(self.accounts, f)

    def load(self):
        try:
            with open("accounts.json") as f:
                self.accounts = json.load(f)
        except IOError as e:
            pass

    def fetch(self, gid, uid):
        return [bill for bill in self.accounts.get(gid, [])
                if bill['uid'] == uid]

    def track(self, gid, uid, amount, description):
        today = datetime.date.today().isoformat()
        bill = dict(uid=uid, amount=amount, description=description, date=today)
        self.accounts.setdefault(gid, []).append(bill)

    def resolve(self, gid):
        balance = {}
        for bill in self.accounts.get(gid, []):
            balance[bill['uid']] = 0
        participants = list(balance.keys())

        if len(participants) == 0:
            return []

        if len(participants) == 1:
            total = 0
            for bill in self.accounts[gid]:
                total += bill['amount']
            return [('World', participants[0], total)]

        nb_others = len(participants) - 1
        for bill in self.accounts[gid]:
            lend = Decimal(bill['amount'])
            debt = lend / nb_others
            for participant in balance.keys():
                if participant == bill['uid']:
                    balance[participant] += lend
                else:
                    balance[participant] -= debt
        return peinard.heuristic(balance)

    def clear(self, gid):
        self.accounts[gid] = []


class Accounter(telepot.aio.helper.ChatHandler):

    fetch_bills_regex = re.compile(r"^@\w+$")  # /ihm @leplatrem
    track_bill_regex = re.compile(r"^(\d+)\s+(\w+)$")  # /ihm 35 t-shit kidz
    total_regex = re.compile(r"^total$")  # /ihm total
    reset_regex = re.compile(r"^reset$")  # /ihm reset

    def __init__(self, seed_tuple, store, **kwargs):
        super(Accounter, self).__init__(seed_tuple, **kwargs)
        self.store = store

    async def on_chat_message(self, msg):
        content_type, chat_type, chat_id = telepot.glance(msg)
        if content_type != 'text':
            return

        uid = msg['from']['username']
        gid = str(msg['chat']['id'])
        cmd = msg['text'].split(' ', 1)
        parameters = cmd[1] if len(cmd) > 1 else ''
        parameters = parameters.strip()

        if cmd[0].strip() != "/ihm":
            return

        print(gid, uid, parameters)

        if self.fetch_bills_regex.match(parameters):
            await self.fetch_bills(gid, parameters[1:])

        elif self.track_bill_regex.match(parameters):
            content = self.track_bill_regex.search(parameters)
            amount, description = content.groups()
            await self.track_bill(gid, uid, int(amount), description)

        elif self.total_regex.match(parameters):
            await self.total(gid)

        elif self.reset_regex.match(parameters):
            await self.clear(gid)

        else:
            message = ("😳?\n"
                       "• /ihm 42 cheese: track bill\n"
                       "• /ihm @username: fetch someone's bills\n"
                       "• /ihm total: current debts\n"
                       "• /ihm reset: clear bills\n")
            await self.sender.sendMessage(message)

    async def fetch_bills(self, gid, uid):
        bills = self.store.fetch(gid, uid)
        if len(bills) == 0:
            await self.sender.sendMessage("No bills found for {} 😕".format(uid))
            return

        message = "\n".join(["• {date}: {amount} ({description})".format(**bill)
                             for bill in bills])
        await self.sender.sendMessage(message)

    async def track_bill(self, gid, uid, amount, description):
        self.store.track(gid, uid, amount, description)
        self.store.save()
        await self.total(gid)

    async def total(self, gid):
        result = self.store.resolve(gid)
        message = "\n".join([" • {} → {}: {}".format(*transaction)
                             for transaction in result])
        await self.sender.sendMessage("🤑\n" + message)

    async def clear(self, gid):
        await self.total(gid)
        self.store.clear(gid)
        self.store.save()
        await self.sender.sendMessage("Bills cleared 👌")



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
