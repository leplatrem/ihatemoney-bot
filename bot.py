# coding: UTF-8
import asyncio
import datetime
import decimal
import json
import math
import re
import sys
from collections import defaultdict
from decimal import Decimal

import telepot
from telepot.aio.delegate import per_chat_id, create_open, pave_event_space


class Store(object):
    def __init__(self):
        self.accounts = {}

    def save(self):
        with open("accounts.json", "w") as f:
            json.dump(self.accounts, f, indent=2)

    def load(self):
        try:
            with open("accounts.json") as f:
                self.accounts = json.load(f)
        except IOError as e:
            pass

    def set_persons(self, gid, uid, nb):
        self.accounts.setdefault(gid, {}).setdefault("participants", {})[uid] = nb

    def list_persons(self, gid):
        return list(self.accounts.get(gid, {}).get("participants", {}).keys())

    def display(self, gid, uid):
        nb_persons = self.accounts.get(gid, {}).get("participants", {})
        nb = nb_persons.get(uid, 1)
        if nb == 0:
            uid += "👻"
        elif nb > 1:
            uid += "(%s👨‍👦‍👦)" % nb
        return uid

    def fetch(self, gid, uid):
        bills = [bill for bill in self.accounts.get(gid, {}).get("bills", [])
                 if bill['uid'] == uid]
        total = 0
        for bill in bills:
            total += bill['amount']
        return total, bills

    def track(self, gid, uid, amount, description):
        today = datetime.date.today().isoformat()
        bill = dict(uid=uid, amount=amount, description=description, date=today)
        self.accounts.setdefault(gid, {}).setdefault("bills", []).append(bill)
        total = sum([b["amount"] for b in self.accounts[gid]["bills"]])
        return total

    def settle(self, gid):
        bills = self.accounts.get(gid, {}).get("bills", [])
        if not bills:
            return 0, set(), []

        balance = defaultdict(int)
        participants = set([bill['uid'] for bill in bills])
        if len(participants) == 1:
            participants.add('World')

        nb_persons = self.accounts.get(gid, {}).get("participants", {})
        total_persons = sum([nb_persons.get(p, 1) for p in participants])

        total = 0
        for bill in bills:
            amount = decimal.Decimal(bill['amount'])
            total += amount

            for participant in participants:
                nb = nb_persons.get(participant, 1)
                share =  amount * nb / total_persons
                if participant == bill['uid']:
                    balance[participant] += share
                else:
                    balance[participant] -= share

        credits = [{"uid": k, "balance": v} for k, v in balance.items() if v > 0]
        debts = [{"uid": k, "balance": v} for k, v in balance.items() if v < 0]

        def exactmatch(credit, debts):
            """Recursively try and find subsets of 'debts' whose sum is equal to credit"""
            if not debts:
                return None
            if debts[0]["balance"] > credit:
                return exactmatch(credit, debts[1:])
            elif debts[0]["balance"] == credit:
                return [debts[0]]
            else:
                matches = exactmatch(credit - debts[0]["balance"], debts[1:])
                if matches:
                    matches.append(debts[0])
                else:
                    matches = exactmatch(credit, debts[1:])
                return matches

        transactions = []

        # Try and find exact matches
        for credit in credits:
            matches = exactmatch(round(credit["balance"], 2), debts)
            if matches:
                for m in matches:
                    transactions.append((self.display(gid, m["uid"]), self.display(gid, credit["uid"]), m["balance"]))
                    debts.remove(m)
                credits.remove(credit)

        # Split any remaining debts & credits
        while credits and debts:
            credit = credits[0]
            debt = debts[0]
            if credit["balance"] > debt["balance"]:
                value = abs(debt["balance"])
                credit["balance"] -= debt["balance"]
                del debts[0]
            else:
                value = credit["balance"]
                debt["balance"] -= credit["balance"]
                del credits[0]
            transactions.append((self.display(gid, debt["uid"]), self.display(gid, credit["uid"]), math.ceil(value)))

        return total, total_persons, transactions

    def clear(self, gid):
        self.accounts.setdefault(gid, {})["bills"] = []


class Accounter(telepot.aio.helper.ChatHandler):

    persons_regex = re.compile(r"^(?P<uid>@\w+)?\s*(?P<nb>\d+) persons$")  # /ihm @leplatrem 3 persons
    fetch_bills_regex = re.compile(r"^@\w+$")  # /ihm @leplatrem
    track_bill_regex = re.compile(r"^(?P<uid>@\w+)?\s*(?P<amount>\d+(\.\d+)?)\s+(?P<description>.+)$")  # /ihm 35.3 t-shit kidz
    settle_regex = re.compile(r"^settle$")  # /ihm settle
    status_regex = re.compile(r"^status$")  # /ihm settle
    reset_regex = re.compile(r"^reset$")  # /ihm reset

    def __init__(self, seed_tuple, store, **kwargs):
        super(Accounter, self).__init__(seed_tuple, **kwargs)
        self.store = store

    async def on_chat_message(self, msg):
        content_type, chat_type, chat_id, msg_date, msg_id = telepot.glance(msg, long=True)
        if content_type != 'text':
            return

        gid = str(msg['chat']['id'])
        cmd = msg['text'].split(' ', 1)
        parameters = cmd[1].strip() if len(cmd) > 1 else ''

        if cmd[0].strip() != "/ihm":
            return

        try:
            uid = msg['from']['username']
        except KeyError:
            uid = None

        print(gid, uid, parameters)

        if self.fetch_bills_regex.match(parameters):
            await self.fetch_bills(gid, parameters[1:])

        elif self.persons_regex.match(parameters):
            content = self.persons_regex.search(parameters)
            if content.group('uid'):
                uid = content.group('uid')[1:]
            if uid is None:
                message = "I need you to have a Telegram username!"
                await self.sender.sendMessage(message)
            else:
                nb = int(content.group('nb'))
                await self.set_persons(gid, uid, nb)

        elif self.track_bill_regex.match(parameters):
            content = self.track_bill_regex.search(parameters)
            if content.group('uid'):
                uid = content.group('uid')[1:]
            if uid is None:
                message = "I need you to have a Telegram username!"
                await self.sender.sendMessage(message)
            else:
                amount = float(content.group('amount'))
                description = content.group('description')
                # If username was put in description, be indulgent and parse it.
                username = re.search(r'@\w+', description or "")
                if username:
                    uid = username.group()
                    description = description.replace(uid, "")
                await self.track_bill(gid, msg_id, uid, amount, description)

        elif self.settle_regex.match(parameters):
            await self.settle(gid)

        elif self.status_regex.match(parameters):
            await self.status(gid)

        elif self.reset_regex.match(parameters):
            await self.clear(gid)

        else:
            message = ("😳?\n"
                       "• `/ihm 42 cheese`: track a bill\n"
                       "• `/ihm @username 42 cheese`: track someone's bill\n"
                       "• `/ihm @username`: show someone's bills\n"
                       "• `/ihm @username 2 persons`: someone pays for a group\n"
                       "• `/ihm settle`: show current debts\n"
                       "• `/ihm status`: show full report\n"
                       "• `/ihm reset`: clear bills\n")
            await self.sender.sendMessage(message, parse_mode="Markdown", reply_to_message_id=msg_id)

    async def set_persons(self, gid, uid, nb):
        self.store.set_persons(gid, uid, nb)
        self.store.save()
        await self.sender.sendMessage("👍")

    async def fetch_bills(self, gid, uid):
        total, bills = self.store.fetch(gid, uid)
        if len(bills) == 0:
            await self.sender.sendMessage("No bills found for {} 😕".format(uid))
            return

        message = "\n".join(["• {date}: {amount} ({description})".format(**bill)
                             for bill in bills])
        message += "\n_______________\n💶 {}".format(total)
        await self.sender.sendMessage(message)

    async def track_bill(self, gid, msg_id, uid, amount, description):
        total = self.store.track(gid, uid, amount, description)
        self.store.save()
        await self.sender.sendMessage("👍 Total: {:0.2f}".format(total), reply_to_message_id=msg_id)

    async def settle(self, gid):
        total, total_persons, transactions = self.store.settle(gid)
        if not total_persons:
            return
        details = "\n".join([" • @{} → @{}: {}".format(*transaction)
                             for transaction in transactions])
        summary = "Total: {:0.2f} 👉 {} each 🤑\n______________\n".format(total, math.ceil(total / total_persons))
        await self.sender.sendMessage(summary + details)

    async def status(self, gid):
        uids = self.store.list_persons(gid)
        for uid in uids:
            await self.fetch_bills(gid, uid)
        await self.settle(gid)

    async def clear(self, gid):
        await self.settle(gid)
        self.store.clear(gid)
        self.store.save()
        await self.sender.sendMessage("Bills cleared 👌")


if __name__ == "__main__":
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
