import html

from db import CURRENCY, money


def esc(value):
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def badge(state):
    return f'<span class="badge b-{esc(state)}">{esc(state)}</span>'


def layout(title, content, user=None, notice=None, error=None):
    nav = ""
    if user:
        if user["role"] == "admin":
            links = [("/", "Overview"), ("/members", "Members"), ("/users", "Logins"),
                     ("/billing", "Billing"), ("/password", "Password")]
        else:
            links = [("/", "My account"), ("/password", "Password")]
        items = "".join(
            f'<a href="{href}" class="nav-link">{esc(label)}</a>' for href, label in links
        )
        nav = f"""
        <nav class="nav">
          <div class="brand"><span class="mark">{esc(CURRENCY)}</span> Fund Ledger</div>
          <div class="nav-links">{items}</div>
          <form class="logout" method="post" action="/logout">
            <input type="hidden" name="csrf" value="{esc(user.get('csrf', ''))}">
            <span class="who">{esc(user['username'])} <em>{esc(user['role'])}</em></span>
            <button class="btn btn-ghost" type="submit">Sign out</button>
          </form>
        </nav>"""

    flash = ""
    if notice:
        flash = f'<div class="flash flash-ok">{esc(notice)}</div>'
    if error:
        flash = f'<div class="flash flash-bad">{esc(error)}</div>'

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} &middot; Fund Ledger</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
{nav}
<main class="wrap">
{flash}
{content}
</main>
<script src="/static/app.js"></script>
</body>
</html>"""
    return body


# ------------------------------------------------------------------ login

def login_page(username=""):
    return f"""
    <div class="signin">
      <div class="signin-card">
        <div class="brand big"><span class="mark">{esc(CURRENCY)}</span> Fund Ledger</div>
        <p class="muted">Sign in with your username and password to see balances and record transactions.</p>
        <form method="post" action="/login" class="stack">
          <label class="field">
            <span>Username</span>
            <input name="username" value="{esc(username)}" autocomplete="username" required autofocus>
          </label>
          <label class="field">
            <span>Password</span>
            <input name="password" type="password" autocomplete="current-password" required>
          </label>
          <button class="btn btn-primary wide" type="submit">Sign in</button>
        </form>
      </div>
    </div>"""


def password_page(user):
    return f"""
    <div class="signin">
      <div class="signin-card">
        <div class="brand big"><span class="mark">{esc(CURRENCY)}</span> Fund Ledger</div>
        <p class="muted">Welcome, <strong>{esc(user['username'])}</strong>. Choose a new password to continue.</p>
        <form method="post" action="/password" class="stack">
          <input type="hidden" name="csrf" value="__CSRF__">
          <label class="field"><span>New password</span>
            <input name="password" type="password" autocomplete="new-password" minlength="6" required autofocus></label>
          <label class="field"><span>Repeat password</span>
            <input name="password2" type="password" autocomplete="new-password" minlength="6" required></label>
          <button class="btn btn-primary wide" type="submit">Save password</button>
        </form>
      </div>
    </div>"""


# ------------------------------------------------------------------ shared

def stat_card(label, value, sub="", tone=""):
    return f"""<div class="stat {tone}">
      <div class="stat-label">{esc(label)}</div>
      <div class="stat-value">{value}</div>
      <div class="stat-sub">{sub}</div>
    </div>"""


def entry_table(entries):
    if not entries:
        return '<p class="muted empty">No transactions recorded yet.</p>'
    rows = []
    for e in reversed(entries):
        if e["type"] == "charge":
            cls, sign, word = "t-charge", "+", "Charge"
        elif e["type"] == "payment":
            cls, sign, word = "t-payment", "\u2212", "Payment"
        else:
            cls, sign, word = "t-payout", "", "Payout"
        amount = f"<span class='{cls}'>{sign}{CURRENCY}{money(e['amount'])}</span>"
        if e["type"] == "payout":
            amount = f"<span class='t-payout'>{CURRENCY}{money(e['amount'])}</span>"
        rows.append(f"""<tr>
          <td class="nowrap">{esc(e['at'])}</td>
          <td>{esc(e['ref'])}</td>
          <td><strong>{esc(word)}</strong> &middot; {esc(e['label'])}</td>
          <td class="num">{amount}</td>
          <td class="num muted">{CURRENCY}{money(e['balance'])}</td>
        </tr>""")
    return f"""<div class="table-scroll"><table class="table">
      <thead><tr><th>Date</th><th>Ref</th><th>Description</th><th class="num">Amount</th><th class="num">Balance</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table></div>"""


def balance_panel(m, viewer="admin"):
    pct = 0
    if m["charged"] > 0:
        pct = max(0, min(100, round(m["paid"] / m["charged"] * 100)))
    due = m["due_date"] or (f"Day {m['due_day']} of each month" if m["due_day"] else "\u2014")
    return f"""
    <div class="balance-panel">
      <div class="balance-main">
        <div class="stat-label">Remaining to be paid</div>
        <div class="balance-big">{CURRENCY}{money(m['remaining'])}</div>
        <div class="bar"><span style="width:{pct}%"></span></div>
        <div class="balance-split">
          <div><span>Charged</span><strong>{CURRENCY}{money(m['charged'])}</strong></div>
          <div><span>Paid</span><strong>{CURRENCY}{money(m['paid'])}</strong></div>
          <div><span>Progress</span><strong>{pct}%</strong></div>
        </div>
      </div>
      <div class="balance-side">
        <div><span>Status</span>{badge(m['state'])}</div>
        <div><span>Payment due</span><strong>{esc(due)}</strong></div>
        <div><span>Fund plan</span><strong>{CURRENCY}{money(m['due_amount'])} / month</strong></div>
        <div><span>Paid out to member</span><strong>{CURRENCY}{money(m.get('disbursed', 0))}</strong></div>
      </div>
    </div>"""


# ------------------------------------------------------------------ admin

def admin_home(stats, members, dues_month, dues_message=None, flash_error=None):
    m = stats["members"]
    rows = []
    for x in members:
        rows.append(f"""<tr>
          <td><a href="/members/{x['id']}">{esc(x['name'])}</a>
              <div class="tiny muted">{esc(x['phone'] or x['email'] or '')}</div></td>
          <td>{badge(x['state'])}</td>
          <td class="num">{CURRENCY}{money(x['charged'])}</td>
          <td class="num">{CURRENCY}{money(x['paid'])}</td>
          <td class="num strong">{CURRENCY}{money(x['remaining'])}</td>
          <td class="num nowrap"><a class="btn btn-sm" href="/members/{x['id']}">Open</a></td>
        </tr>""")

    recent = "".join(
        f"""<li class="feed-item"><span class="dot d-{esc(r['type'])}"></span>
            <div><strong>{esc(r['member'])}</strong> &middot; {esc(r['ref'] or '')}
            <div class="tiny muted">{esc(r['at'])}</div></div>
            <b class="num">{CURRENCY}{money(r['amount'])}</b></li>"""
        for r in stats["recent"]
    ) or '<li class="muted">Nothing recorded yet.</li>'

    content = f"""
    <div class="page-head">
      <div><h1>Overview</h1><p class="muted">Everything owed, collected and owed back across the fund.</p></div>
      <div class="actions">
        <a class="btn" href="/members/new">+ New member</a>
        <a class="btn" href="/export.csv">Export CSV</a>
      </div>
    </div>

    <div class="grid grid-4">
      {stat_card('Outstanding balance', f'{CURRENCY}{money(stats["outstanding"])}', 'sum of all member balances', 'warn')}
      {stat_card('Collected this month', f'{CURRENCY}{money(stats["month_paid"])}', f'{stats["month_count"]} payment(s)')}
      {stat_card('Active members', str(m), 'with a login', 'ok')}
      {stat_card('Disbursed to members', f'{CURRENCY}{money(stats["disbursed"])}', 'payouts & refunds')}
    </div>

    <div class="panel">
      <div class="panel-head">
        <h2>Run monthly dues</h2>
        <form method="post" action="/billing/run" class="inline-form">
          <input type="hidden" name="csrf" value="__CSRF__">
          <input type="month" name="month" value="{esc(dues_month)}" required>
          <input name="amount" placeholder="amount (blank = member plan)" inputmode="decimal">
          <button class="btn btn-primary" type="submit">Generate charges</button>
        </form>
      </div>
      {f'<div class="flash flash-ok">{esc(dues_message)}</div>' if dues_message else ''}
      {f'<div class="flash flash-bad">{esc(flash_error)}</div>' if flash_error else ''}
      <p class="muted">Creates one <em>Dues</em> charge per active member for that month. Already-recorded months are skipped.</p>
    </div>

    <div class="two-col">
      <div class="panel">
        <div class="panel-head"><h2>Members</h2><a class="btn btn-sm" href="/members">See all</a></div>
        <div class="table-scroll"><table class="table">
          <thead><tr><th>Member</th><th>State</th><th class="num">Charged</th><th class="num">Paid</th><th class="num">Remaining</th><th></th></tr></thead>
          <tbody>{''.join(rows) or '<tr><td colspan="6" class="muted">No members yet.</td></tr>'}</tbody>
        </table></div>
      </div>
      <div class="panel">
        <div class="panel-head"><h2>Recent activity</h2></div>
        <ul class="feed">{recent}</ul>
      </div>
    </div>"""
    return content


def billing_page(months, month, notice=None, error=None):
    rows = "".join(
        f"""<tr><td class="nowrap">{esc(x['month'])}</td>
            <td class="num">{x['n']}</td>
            <td class="num strong">{CURRENCY}{money(x['total'])}</td></tr>"""
        for x in months
    )
    form = f"""
    <form method="post" action="/billing/run" class="inline-form">
      <input type="hidden" name="csrf" value="__CSRF__">
      <input type="month" name="month" value="{esc(month)}" required>
      <input name="amount" placeholder="amount (blank = member plan)" inputmode="decimal">
      <button class="btn btn-primary" type="submit">Generate charges</button>
    </form>"""
    return f"""
    <div class="page-head">
      <div><h1>Billing</h1><p class="muted">Raise this month's dues and review what has come in.</p></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Run monthly dues</h2>{form}</div>
      {f'<div class="flash flash-ok">{esc(notice)}</div>' if notice else ''}
      {f'<div class="flash flash-bad">{esc(error)}</div>' if error else ''}
      <p class="muted">Creates one <em>Dues</em> charge for every active member with a recurring amount.
      Months already recorded are skipped, so it is safe to press more than once.</p>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Collected by month</h2></div>
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Month</th><th class="num">Payments</th><th class="num">Total in</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="3" class="muted">No payments recorded yet.</td></tr>'}</tbody>
      </table></div>
    </div>"""


def members_page(members):
    rows = "".join(
        f"""<tr>
          <td><a href="/members/{x['id']}">{esc(x['name'])}</a></td>
          <td class="muted">{esc(x['phone'])} {esc(x['email'])}</td>
          <td>{badge(x['state'])}</td>
          <td class="num">{esc(x['due_day'] or ('\u2014'))}</td>
          <td class="num">{CURRENCY}{money(x['charged'])}</td>
          <td class="num">{CURRENCY}{money(x['paid'])}</td>
          <td class="num strong">{CURRENCY}{money(x['remaining'])}</td>
          <td class="num">{esc(str(x['login_count']))}</td>
        </tr>"""
        for x in members
    )
    return f"""
    <div class="page-head">
      <div><h1>Members</h1><p class="muted">Every person in the fund and what they still owe.</p></div>
      <div class="actions"><a class="btn" href="/export.csv">Export CSV</a>
      <a class="btn btn-primary" href="/members/new">+ New member</a></div>
    </div>
    <div class="panel"><div class="table-scroll"><table class="table">
      <thead><tr><th>Name</th><th>Contact</th><th>State</th><th class="num">Due day</th>
      <th class="num">Charged</th><th class="num">Paid</th><th class="num">Remaining</th><th class="num">Logins</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="8" class="muted">No members yet. Add your first one.</td></tr>'}</tbody>
    </table></div></div>"""


def member_form(member, error=None):
    is_new = member is None
    m = member or {"name": "", "phone": "", "email": "", "note": "", "due_amount": 0,
                   "due_day": "", "due_date": "", "status": "active"}
    if is_new:
        link_block = f"""
        <fieldset class="fieldset">
          <legend>Login for this member</legend>
          <div class="two">
            <label class="field"><span>Username</span>
              <input name="username" autocomplete="off" required></label>
            <label class="field"><span>Temporary password</span>
              <input name="password" type="text" autocomplete="off" minlength="6" required></label>
          </div>
          <p class="muted tiny">The member signs in with this. They will be asked to change the password on first sign-in.</p>
        </fieldset>"""
    else:
        link_block = ""
    return f"""
    <div class="page-head"><div>
      <h1>{'New member' if is_new else 'Edit member'}</h1>
      <p class="muted">{esc(m['name']) if not is_new else 'Add a person to the fund and set their payment plan.'}</p>
    </div></div>
    <form method="post" action="{'/members/new' if is_new else '/members/%s/edit' % m['id']}" class="panel stack">
      <input type="hidden" name="csrf" value="__CSRF__">
      <fieldset class="fieldset"><legend>Details</legend>
        <div class="two">
          <label class="field"><span>Full name *</span><input name="name" value="{esc(m['name'])}" required></label>
          <label class="field"><span>Phone</span><input name="phone" value="{esc(m['phone'])}"></label>
        </div>
        <div class="two">
          <label class="field"><span>Email</span><input name="email" type="email" value="{esc(m['email'])}"></label>
          <label class="field"><span>Status</span>
            <select name="status">
              <option value="active" {'selected' if m['status'] == 'active' else ''}>Active</option>
              <option value="paused" {'selected' if m['status'] == 'paused' else ''}>Paused</option>
              <option value="closed" {'selected' if m['status'] == 'closed' else ''}>Closed</option>
            </select></label>
        </div>
        <label class="field"><span>Notes</span><textarea name="note" rows="2">{esc(m['note'])}</textarea></label>
      </fieldset>
      <fieldset class="fieldset"><legend>Payment plan</legend>
        <div class="two">
          <label class="field"><span>Recurring amount ({esc(CURRENCY)})</span>
            <input name="due_amount" value="{money(m['due_amount'] or 0)}" inputmode="decimal"></label>
          <label class="field"><span>Due day of month (1&ndash;28)</span>
            <input name="due_day" value="{esc(m['due_day'] or '')}" inputmode="numeric" placeholder="e.g. 5"></label>
        </div>
        <label class="field"><span>Final deadline (optional)</span>
          <input type="date" name="due_date" value="{esc(m['due_date'] or '')}"></label>
        <p class="muted tiny">A member is marked <strong>overdue</strong> while they still owe and the due day / deadline has passed.</p>
      </fieldset>
      {link_block}
      <div class="form-actions">
        <a class="btn" href="{'/members/new' if is_new else '/members/%s' % m['id']}">Cancel</a>
        <button class="btn btn-primary" type="submit">{'Create member' if is_new else 'Save changes'}</button>
      </div>
    </form>"""


def member_detail(m, entries, linked, flash=None, flash_error=None):
    user_rows = "".join(
        f'<li><a href="/users">u/{esc(u["username"])}</a> <span class="tiny muted">{esc(u["role"])}</span></li>'
        for u in linked
    ) or '<li class="muted">No login yet.</li>'

    return f"""
    <div class="page-head">
      <div>
        <p class="crumbs"><a href="/members">&larr; Members</a></p>
        <h1>{esc(m['name'])} {badge(m['state'])}</h1>
        <p class="muted">{esc(m['phone'])} {esc(m['email'])} &middot; joined {esc(m['created_at'][:10])}</p>
      </div>
      <div class="actions">
        <a class="btn" href="/members/{m['id']}/edit">Edit</a>
        <form method="post" action="/members/{m['id']}/delete" class="inline-form"
              data-confirm="Remove {esc(m['name'])} and all of their transactions? This cannot be undone.">
          <input type="hidden" name="csrf" value="__CSRF__">
          <button class="btn btn-danger" type="submit">Delete</button>
        </form>
      </div>
    </div>

    {balance_panel(m)}

    <div class="two-col">
      <div class="panel">
        <div class="panel-head"><h2>Record a transaction</h2></div>
        <div class="tabs">
          <button class="tab is-active" data-tab="pay">Payment in</button>
          <button class="tab" data-tab="chg">Add charge</button>
          <button class="tab" data-tab="pay_out">Payout</button>
        </div>

        <form method="post" action="/members/{m['id']}/payments" class="tab-panel is-active" data-panel="pay">
          <input type="hidden" name="csrf" value="__CSRF__">
          <div class="two">
            <label class="field"><span>Amount ({esc(CURRENCY)}) *</span>
              <input name="amount" inputmode="decimal" placeholder="0.00" required></label>
            <label class="field"><span>Date paid</span>
              <input type="date" name="paid_at"></label>
          </div>
          <div class="two">
            <label class="field"><span>Method</span>
              <select name="method"><option>cash</option><option>bank</option>
                <option>mobile money</option><option>cheque</option><option>other</option></select></label>
            <label class="field"><span>Reference</span><input name="reference" placeholder="receipt no."></label>
          </div>
          <label class="field"><span>Note</span><input name="note" placeholder="optional"></label>
          <button class="btn btn-primary wide" type="submit">Record payment</button>
        </form>

        <form method="post" action="/members/{m['id']}/charges" class="tab-panel" data-panel="chg">
          <input type="hidden" name="csrf" value="__CSRF__">
          <div class="two">
            <label class="field"><span>Amount ({esc(CURRENCY)}) *</span>
              <input name="amount" inputmode="decimal" placeholder="0.00" required></label>
            <label class="field"><span>Type</span>
              <select name="kind"><option value="dues">dues</option>
                <option value="penalty">penalty / fine</option><option value="other">other</option></select></label>
          </div>
          <label class="field"><span>Description *</span>
            <input name="description" placeholder="Late fee, extra contribution..." required></label>
          <button class="btn btn-primary wide" type="submit">Add charge</button>
        </form>

        <form method="post" action="/members/{m['id']}/payouts" class="tab-panel" data-panel="pay_out">
          <input type="hidden" name="csrf" value="__CSRF__">
          <div class="two">
            <label class="field"><span>Amount ({esc(CURRENCY)}) *</span>
              <input name="amount" inputmode="decimal" placeholder="0.00" required></label>
            <label class="field"><span>Date paid</span>
              <input type="date" name="paid_at"></label>
          </div>
          <label class="field"><span>Note *</span>
            <input name="note" placeholder="Dividend, refund, payout..." required></label>
          <p class="muted tiny">Payouts are money handed back to the member. They show in history but do not change the remaining balance.</p>
          <button class="btn btn-primary wide" type="submit">Record payout</button>
        </form>
      </div>

      <div class="panel">
        <div class="panel-head"><h2>Linked login</h2></div>
        <ul class="plain-list">{user_rows}</ul>
        <div class="panel-head" style="margin-top:18px"><h2>Summary</h2></div>
        <ul class="kv">
          <li><span>Charges</span><strong>{CURRENCY}{money(m['charged'])}</strong></li>
          <li><span>Payments</span><strong>{CURRENCY}{money(m['paid'])}</strong></li>
          <li><span>Remaining</span><strong class="strong">{CURRENCY}{money(m['remaining'])}</strong></li>
          <li><span>Payouts</span><strong>{CURRENCY}{money(m.get('disbursed', 0))}</strong></li>
          <li><span>Transactions</span><strong>{len(entries)}</strong></li>
        </ul>
        {f'<div class="flash flash-ok">{esc(flash)}</div>' if flash else ''}
        {f'<div class="flash flash-bad">{esc(flash_error)}</div>' if flash_error else ''}
      </div>
    </div>

    <div class="panel">
      <div class="panel-head"><h2>History</h2></div>
      {entry_table(entries)}
    </div>"""


def users_page(users, error=None, notice=None):
    rows = "".join(
        f"""<tr>
          <td><strong>{esc(u['username'])}</strong></td>
          <td>{badge(u['role'])}</td>
          <td>{esc(u['member_name'] or ('\u2014'))}</td>
          <td class="muted">{esc(u['last_login'] or 'never')}</td>
          <td class="muted">{esc(u['created_at'][:10])}</td>
          <td class="num nowrap">
            <form method="post" action="/users/{u['id']}/reset" class="inline-form">
              <input type="hidden" name="csrf" value="__CSRF__">
              <button class="btn btn-sm" type="submit">Reset password</button>
            </form>
          </td>
        </tr>"""
        for u in users
    )
    return f"""
    <div class="page-head">
      <div><h1>Logins</h1><p class="muted">Usernames and passwords people use to enter the site.</p></div>
      <div class="actions"><a class="btn btn-primary" href="/users/new">+ New login</a></div>
    </div>
    <div class="panel">
      <div class="table-scroll"><table class="table">
        <thead><tr><th>Username</th><th>Role</th><th>Member</th><th>Last sign-in</th><th>Created</th><th></th></tr></thead>
        <tbody>{rows or '<tr><td colspan="6" class="muted">No users.</td></tr>'}</tbody>
      </table></div>
    </div>"""


def user_form(members, error=None, values=None):
    v = values or {"username": "", "password": "", "role": "member", "member_id": ""}
    options = ['<option value="">(no linked member)</option>'] + [
        f'<option value="{x["id"]}" {"selected" if str(x["id"]) == str(v["member_id"]) else ""}>{esc(x["name"])}</option>'
        for x in members
    ]
    return f"""
    <div class="page-head"><div>
      <p class="crumbs"><a href="/users">&larr; Logins</a></p>
      <h1>New login</h1><p class="muted">Give someone a username and password to sign in with.</p>
    </div></div>
    <form method="post" action="/users/new" class="panel stack">
      <input type="hidden" name="csrf" value="__CSRF__">
      <div class="two">
        <label class="field"><span>Username *</span><input name="username" value="{esc(v['username'])}" required></label>
        <label class="field"><span>Temporary password *</span>
          <input name="password" type="text" minlength="6" required></label>
      </div>
      <div class="two">
        <label class="field"><span>Role</span>
          <select name="role">
            <option value="member" {'selected' if v['role'] == 'member' else ''}>Member (own balance only)</option>
            <option value="admin" {'selected' if v['role'] == 'admin' else ''}>Admin (everything)</option>
          </select></label>
        <label class="field"><span>Linked member</span><select name="member_id">{''.join(options)}</select></label>
      </div>
      <div class="form-actions">
        <a class="btn" href="/users">Cancel</a>
        <button class="btn btn-primary" type="submit">Create login</button>
      </div>
    </form>"""


# ------------------------------------------------------------------ member

def member_home(m, entries, user, flash=None, flash_error=None):
    if m is None:
        return """
        <div class="page-head"><div><h1>Your account</h1>
        <p class="muted">Your login is not linked to a member record yet. Ask the administrator to link it.</p></div></div>"""
    pct = 0
    if m["charged"] > 0:
        pct = max(0, min(100, round(m["paid"] / m["charged"] * 100)))
    return f"""
    <div class="page-head">
      <div><h1>Hello, {esc(m['name'])}</h1>
      <p class="muted">Here is exactly where you stand with the fund.</p></div>
    </div>
    <div class="grid grid-3">
      {stat_card('Remaining to be paid', f'{CURRENCY}{money(m["remaining"])}', 'amount still outstanding', 'warn' if m['remaining'] > 0 else 'ok')}
      {stat_card('Paid so far', f'{CURRENCY}{money(m["paid"])}', f'{pct}% of {CURRENCY}{money(m["charged"])} charged', 'ok')}
      {stat_card('Status', esc(m['state']).upper(), 'payment standing', 'ok' if m['state'] == 'settled' else 'warn')}
    </div>
    {balance_panel(m, viewer='member')}
    <div class="panel">
      <div class="panel-head"><h2>Your transactions</h2><span class="muted tiny">newest first</span></div>
      {entry_table(entries)}
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Change your password</h2></div>
      <form method="post" action="/password" class="inline-form-form">
        <input type="hidden" name="csrf" value="__CSRF__">
        <div class="two">
          <label class="field"><span>New password</span>
            <input name="password" type="password" minlength="6" required></label>
          <label class="field"><span>Repeat password</span>
            <input name="password2" type="password" minlength="6" required></label>
        </div>
        <button class="btn btn-primary" type="submit">Update password</button>
      </form>
    </div>"""


def not_found(message="Page not found"):
    return f"""
    <div class="signin"><div class="signin-card">
      <div class="brand big"><span class="mark">{esc(CURRENCY)}</span></div>
      <h1>{esc(message)}</h1>
      <p class="muted">The page you asked for does not exist.</p>
      <a class="btn btn-primary wide" href="/">Back to home</a>
    </div></div>"""
