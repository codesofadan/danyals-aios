"""Build the REVISED client-facing access-requirements PDF (house style)."""
import pathlib

import data2 as D

SP = pathlib.Path(__file__).parent
FONTCSS = pathlib.Path(r"C:/Users/adan/.claude/assets/bricolage-grotesque.css").read_text(
    encoding="utf-8"
)
OUT = SP / "access-requirements-v2.html"
T = D.TOTALS


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def short(u):
    u = (u or "").replace("https://", "").replace("http://", "").rstrip("/")
    return u[:34]


PH = '<div class="ph"><span>AIOS &middot; Access &amp; Accounts</span><span>{}</span></div>'

# ============================================================ 1. cover
cover = f"""
<section class="page cover">
  <div class="cov-top">
    <div class="cov-eyebrow">Prepared for Danyal &middot; Revision 2</div>
    <div class="cov-rule"></div>
  </div>
  <div class="cov-mid">
    <h1 class="cov-title">Access &amp;<br>Accounts</h1>
    <p class="cov-sub">Two things we need from you — and the {T['accounts_total']} platform
      accounts the extension publishes through.</p>
  </div>
  <div class="cov-foot">
    <div class="cov-stats">
      <div class="cov-stat"><b>2</b><span>things still needed</span></div>
      <div class="cov-stat"><b>{T['accounts_total']}</b><span>platform accounts to create</span></div>
      <div class="cov-stat"><b>0</b><span>client modules to connect</span></div>
    </div>
    <div class="cov-note">Replaces revision 1. Everything the old version asked for that
      this platform does not actually have has been removed — page 5 lists what and why.</div>
  </div>
</section>
"""

# ============================================================ 2. at a glance
glance = f"""
<section class="page">
  {PH.format('At a glance')}
  <h2 class="sec">At a glance</h2>
  <p class="lede">The list is short. Two credentials, then accounts on the platforms we
    publish to. Nothing else is asked of you.</p>

  <div class="flow">
    <div class="flow-step">
      <div class="fs-n">1</div>
      <div class="fs-b"><b>DataForSEO</b>
        <span>The SEO data source. Never supplied — we are funding it ourselves today.</span></div>
    </div>
    <div class="flow-step">
      <div class="fs-n">2</div>
      <div class="fs-b"><b>A working email account</b>
        <span>The one sent recently does not authenticate. Every account signup needs it.</span></div>
    </div>
    <div class="flow-step">
      <div class="fs-n">3</div>
      <div class="fs-b"><b>{T['accounts_total']} platform accounts</b>
        <span>{T['cit_signups']} citation directories + {T['web2_accounts']} Web 2.0
          platforms. Created once, used by the extension forever after.</span></div>
    </div>
    <div class="flow-step">
      <div class="fs-n">4</div>
      <div class="fs-b"><b>Each client's business record</b>
        <span>Name, address, phone, hours, categories, description, logo. Entered once per
          client — every submission is filled from it, so the details never drift.</span></div>
    </div>
    <div class="flow-step done">
      <div class="fs-n">&#10003;</div>
      <div class="fs-b"><b>Everything else — already in place</b>
        <span>{T['installed_keys']} platform keys are installed and running on our side.</span></div>
    </div>
  </div>

  <div class="two">
    <div class="card-dark">
      <div class="cd-h">What changed in this revision</div>
      <p>Revision 1 asked for {T['removed']} things this platform does not have or does not
        need — Google Business Profile, website&nbsp;/&nbsp;CMS, Analytics and Search Console
        modules among them. <b>All {T['removed']} are removed.</b> What replaced them is the
        one ask that was missing: the SEO data API.</p>
    </div>
    <div class="card-tint">
      <div class="ct-h">The rule that runs the whole system</div>
      <ul class="tick">
        <li><b>The extension is the publisher.</b> Every citation and every Web 2.0 post
          goes out through it.</li>
        <li><b>Direct APIs are a fallback</b>, never the path — they do not get near a
          100% success rate.</li>
        <li><b>An operator presses submit.</b> Always a person, in their own browser.</li>
      </ul>
    </div>
  </div>
</section>
"""

# ============================================================ 3. what we need
need_cards = "".join(
    f"""<div class="needcard">
      <div class="nc-top">
        <div><div class="nc-name">{esc(n['name'])}</div>
          <div class="nc-area">{esc(n['area'])}</div></div>
        <span class="pill pneed">Needed</span>
      </div>
      <div class="nc-grid">
        <div><b>What it powers</b><span>{esc(n['powers'])}</span></div>
        <div><b>Why we are asking</b><span>{esc(n['why'])}</span></div>
        <div><b>Without it</b><span>{esc(n['without'])}</span></div>
        <div><b>Where / cost</b><span>{esc(n['where'])} &middot; {esc(n['cost'])}</span></div>
      </div>
      <div class="nc-key">{esc(n['key'])}</div>
    </div>"""
    for n in D.NEEDED
)

needed = f"""
<section class="page">
  {PH.format('1 &middot; What we still need')}
  <h2 class="sec">What we still need</h2>
  <p class="lede">Two items. One key, one mailbox. Both are agency-level — one of each
    covers every client.</p>
  <div class="needs">{need_cards}</div>
</section>
"""

# ============================================================ 4. installed
inst_cards = "".join(
    f"""<div class="acard ok">
      <div class="ac-top"><b>{esc(nm)}</b><span class="pill pok">In place</span></div>
      <div class="ac-p">{esc(p)}</div>
      <div class="ac-k">{esc(k)}</div>
    </div>"""
    for nm, cat, p, k in D.INSTALLED
)

installed = f"""
<section class="page">
  {PH.format('Already running')}
  <h2 class="sec">Already installed</h2>
  <p class="lede">{T['installed_keys']} keys, all live on our side, all covering every
    client from a single account.</p>
  <div class="agrid">{inst_cards}</div>
  <div class="card-dark wide">
    <div class="cd-h">A note on the AI layer</div>
    <p>All model calls run through <b>AgentRouter</b> rather than straight to Anthropic —
      same Claude models, one router in front, so a provider or quota problem is a routing
      change instead of a redeploy. The key and the base URL are both set.</p>
  </div>
</section>
"""

# ============================================================ 5. removed
rem_rows = "".join(
    f"""<div class="crow">
      <div class="cr-n">{esc(n)}</div>
      <div class="cr-arrow">&times;</div>
      <div class="cr-c">{esc(r)}</div>
    </div>"""
    for n, r in D.REMOVED
)

removed = f"""
<section class="page">
  {PH.format('Removed from the ask')}
  <h2 class="sec">Not part of this platform</h2>
  <p class="lede">Revision 1 asked for all of these. None of them exist here, or none of
    them are needed. They are listed rather than quietly dropped, so the change is visible.</p>
  <div class="ctable">{rem_rows}</div>
  <div class="card-dark wide">
    <div class="cd-h">Why this matters more than it looks</div>
    <p>Asking a client for Google Business Profile, Analytics and Search Console access
      implies four modules that read and report on them. This platform has none of the four.
      Removing the ask keeps the document honest about what actually runs.</p>
  </div>
</section>
"""

# ============================================================ 6. the extension flow
extension = f"""
<section class="page">
  {PH.format('2 &middot; How publishing works')}
  <h2 class="sec">Everything goes<br>through the extension</h2>
  <p class="lede">One lane for citations, one for Web 2.0 — the same mechanism underneath.
    The operator is logged in; the extension does the typing.</p>

  <div class="browser">
    <div class="br-bar"><span class="dot r"></span><span class="dot y"></span>
      <span class="dot g"></span>
      <div class="br-url">directory.example.com/add-listing</div></div>
    <div class="br-body">
      <div class="br-page">
        <div class="skel w60 h18"></div>
        <div class="field"><i>Business name</i><b>Acme Plumbing Co</b></div>
        <div class="field"><i>Address</i><b>221 Baker Street, Springfield</b></div>
        <div class="field"><i>Phone</i><b>+1 555 0142</b></div>
        <div class="field"><i>Description</i><b>Licensed plumbing and drainage&hellip;</b></div>
        <div class="field empty"><i>Category</i><b class="wait">matching&hellip;</b></div>
        <div class="submit">Submit listing</div>
      </div>
      <div class="br-panel">
        <div class="bp-h">AIOS</div>
        <div class="bp-tabs"><span class="on">Citations</span><span>Web 2.0</span></div>
        <div class="bp-task">Acme Plumbing Co<em>Task 14 of 37</em></div>
        <div class="bp-row ok">Name &middot; filled</div>
        <div class="bp-row ok">Address &middot; filled</div>
        <div class="bp-row ok">Phone &middot; filled</div>
        <div class="bp-row ok">Description &middot; filled</div>
        <div class="bp-row work">Category &middot; AI matching</div>
        <div class="bp-cta">You press submit</div>
      </div>
    </div>
  </div>

  <div class="cflow">
    <div class="cf"><div class="cf-n">1</div><b>Content is made in AIOS</b>
      <span>Article, title, body, images, business record — approved before it moves.</span></div>
    <div class="cf-a">&rarr;</div>
    <div class="cf"><div class="cf-n">2</div><b>Copied into the extension</b>
      <span>Every block is carried in the side panel, ready to place.</span></div>
    <div class="cf-a">&rarr;</div>
    <div class="cf"><div class="cf-n">3</div><b>Operator opens the platform</b>
      <span>Any directory, any Web 2.0 site — in their own logged-in browser.</span></div>
    <div class="cf-a">&rarr;</div>
    <div class="cf"><div class="cf-n">4</div><b>Fields fill themselves</b>
      <span>Known spec first, then the page's own attributes, then AI for the rest.</span></div>
    <div class="cf-a">&rarr;</div>
    <div class="cf"><div class="cf-n">5</div><b>Submit &amp; verify</b>
      <span>A person submits; the public URL is fetched and checked before it counts.</span></div>
  </div>
</section>
"""

# ============================================================ 7. extension vs api
api_pct = round(T["web2_api_fallback"] / T["web2_use"] * 100)
vs = f"""
<section class="page">
  {PH.format('Extension first, API second')}
  <h2 class="sec">Why the extension,<br>not the API</h2>
  <p class="lede">Direct publishing APIs exist for {T['web2_api_fallback']} of the
    {T['web2_use']} Web 2.0 platforms we use — about {api_pct}%. They are useful. They are
    not reliable enough to be the path.</p>

  <div class="vs">
    <div class="vs-col good">
      <div class="vs-h">The extension &mdash; the main lane</div>
      <ul class="tick">
        <li>Works on <b>every</b> platform, API or not</li>
        <li>The operator is already logged in — no token to expire</li>
        <li>Survives a redesign: fields are re-read, not hard-coded</li>
        <li>A person reviews before anything is published</li>
        <li>Same mechanism for citations and Web 2.0</li>
      </ul>
    </div>
    <div class="vs-col warn">
      <div class="vs-h">Direct APIs &mdash; the fallback</div>
      <ul class="tick">
        <li>Only {T['web2_api_fallback']} of {T['web2_use']} platforms offer one</li>
        <li>Tokens expire, get revoked, or need app review</li>
        <li>Rate limits and silent rejections are common</li>
        <li>Nowhere near a 100% success rate on its own</li>
        <li>Used when it works; the extension picks up when it does not</li>
      </ul>
    </div>
  </div>

  <div class="covbars">
    <div class="cbar"><span>Extension can publish</span>
      <i style="width:100%"></i><em>{T['web2_use']} / {T['web2_use']}</em></div>
    <div class="cbar alt"><span>Direct API available</span>
      <i style="width:{api_pct}%"></i><em>{T['web2_api_fallback']} / {T['web2_use']}</em></div>
    <div class="cbar"><span>Extension covers citations</span>
      <i style="width:100%"></i><em>{T['cit_accounts']} / {T['cit_accounts']}</em></div>
    <div class="cbar alt"><span>Citation submission APIs</span>
      <i style="width:1%"></i><em>2 / {T['cit_accounts']}</em></div>
  </div>

  <div class="card-dark wide">
    <div class="cd-h">Citations, specifically</div>
    <p>There is effectively no submission API for directories — two of the
      {T['cit_accounts']} we submit to offer one. {T['cit_captcha']} of them put a CAPTCHA in the way, and
      solving it with a bot breaks their terms. So the extension is not a compromise here;
      it is the only route that leaves a listing safe from removal.</p>
  </div>
</section>
"""


# ============================================================ 8-9. web 2.0 accounts
def plat_card(r):
    return (f'<div class="pcard2"><b>{esc(r["name"])}</b>'
            f'<span>{esc(short(r["signup"]) or "no signup page")}</span></div>')


def plat_grid(rows, cols=4):
    return f'<div class="pgrid4">{"".join(plat_card(r) for r in rows)}</div>'


w2_high = D.W2_BY_AUTH["high"]
w2_med = D.W2_BY_AUTH["medium"]
w2_low = D.W2_BY_AUTH["low"]

web2a = f"""
<section class="page">
  {PH.format('3 &middot; Web 2.0 accounts')}
  <h2 class="sec">Web 2.0 — where to<br>create accounts</h2>
  <p class="lede">{T['web2_use']} platforms are in use. {T['web2_accounts']} need an account
    made once, by hand, in a browser. After that the extension publishes into them.</p>

  <div class="stats4">
    <div class="st"><b>{T['web2_use']}</b><span>platforms in use</span></div>
    <div class="st"><b>{T['web2_accounts']}</b><span>need an account</span></div>
    <div class="st"><b>{T['web2_api_fallback']}</b><span>also have an API fallback</span></div>
    <div class="st"><b>{T['web2_excluded']}</b><span>deliberately excluded</span></div>
  </div>

  <div class="sub">High authority — {len(w2_high)} &middot; start here</div>
  {plat_grid(w2_high)}

  <div class="sub sub2">Lower authority — {len(w2_low)} &middot; volume and spread</div>
  {plat_grid(w2_low)}
</section>
"""

excl_names = ", ".join(r["name"] for r in D.W2_EXCL)
web2b = f"""
<section class="page">
  {PH.format('3 &middot; Web 2.0 accounts')}
  <h2 class="sec">Web 2.0 — the rest</h2>
  <p class="lede">{len(w2_med)} mid-authority platforms. Same rule: one account each, made
    by hand once.</p>
  {plat_grid(w2_med)}

  <div class="card-tint wide">
    <div class="ct-h">Excluded on purpose — {T['web2_excluded']}</div>
    <p class="plain">{esc(excl_names)}</p>
    <div class="ct-f">Paste sites, bookmarking and curation services. Catalogued so the
      exclusion is visible rather than looking like an oversight — do not make accounts here.</div>
  </div>
</section>
"""


# ============================================================ 10-12. citations
def cit_overview():
    mk = D.CIT_BY_MARKET
    order = ["US", "GLOBAL", "CA", "AU", "UK"]
    bars = "".join(
        f'<div class="bar"><span>{m}</span>'
        f'<i style="width:{len(mk.get(m, [])) / 86 * 100:.0f}%"></i>'
        f'<em>{len(mk.get(m, []))}</em></div>'
        for m in order
    )
    core = D.CIT_BY_TIER["core"]
    core_cards = "".join(
        f'<div class="pcard2 {"agg" if r["aggregator"] else "core"}">'
        f'<b>{esc(r["name"])}</b><span>{esc(short(r["url"]))}'
        f'{" &middot; no account" if r["aggregator"] else ""}</span></div>'
        for r in core
    )
    core_agg = sum(1 for r in core if r["aggregator"])
    multi = sorted((r for r in D.CIT_SIGNUPS if len(r["also"]) > 1),
                   key=lambda r: -len(r["also"]))[:8]
    multi_rows = "".join(
        f'<div class="dd"><b>{esc(r["host"])}</b>'
        + "".join(f'<span>{esc(m)}</span>' for m in dict.fromkeys(r["also"]))
        + f'<em>{len(r["also"])}&rarr;1</em></div>'
        for r in multi
    )
    return f"""
<section class="page">
  {PH.format('4 &middot; Citation accounts')}
  <h2 class="sec">Citations — where to<br>create accounts</h2>
  <p class="lede">{T['cit_total']} directory listings are live in the registry. They
    resolve to <b>{T['cit_signups']} sign-ups</b> — one account per domain, because a
    Brownbook UK listing and a Brownbook Canada listing come from the same login.</p>

  <div class="stats4">
    <div class="st"><b>{T['cit_total']}</b><span>listings in the registry</span></div>
    <div class="st"><b>{T['cit_signups']}</b><span>accounts to actually create</span></div>
    <div class="st"><b>{T['cit_captcha']}</b><span>put a CAPTCHA in the way</span></div>
    <div class="st"><b>{T['cit_aggregator']}</b><span>need nothing from you</span></div>
  </div>

  <div class="sub">One login can cover several markets</div>
  <div class="dedupe">{multi_rows}</div>

  <div class="two">
    <div class="card-tint">
      <div class="ct-h">By market</div>
      <div class="bars">{bars}</div>
      <div class="ct-f">A client only needs the markets they trade in — a UK business
        works the 23 UK plus the 35 global entries, not all {T['cit_total']}.</div>
    </div>
    <div class="card-dark">
      <div class="cd-h">Create accounts in priority order</div>
      <p>The {len(core)} core directories on the next page carry most of the weight — they
        are the ones the aggregators and Google actually read. Work down from there; the
        tier-2 list behind them is volume, not leverage.</p>
      <p style="margin-top:4mm">A CAPTCHA is not a blocker in this model. The operator is
        already on the page and solves it the way any person would — which is exactly why
        no listing here is ever at risk of being pulled for how it was created.</p>
    </div>
  </div>
</section>

<section class="page">
  {PH.format('4 &middot; Citation accounts')}
  <h2 class="sec">Citations — core {len(core)}</h2>
  <p class="lede">Do these first. {len(core) - core_agg} need an account;
    the {core_agg} marked <b>no account</b> are fed from a data partner and need nothing
    from you at all.</p>
  <div class="pgrid4">{core_cards}</div>
</section>
"""


def cit_list_pages():
    core_hosts = {D.host_of(r["url"]) for r in D.CIT_BY_TIER["core"]}
    rest = [r for r in D.CIT_SIGNUPS if r["host"] not in core_hosts]
    per = 67
    chunks = [rest[i:i + per] for i in range(0, len(rest), per)]
    pages = []
    for n, ch in enumerate(chunks, start=1):
        items = "".join(
            f'<li><b>{esc(r["name"])}</b> <em>{esc(r["host"])}</em></li>' for r in ch
        )
        pages.append(f"""
<section class="page">
  {PH.format('4 &middot; Citation accounts')}
  <h2 class="sec">Citations — the other {len(rest)}{' (cont.)' if n > 1 else ''}</h2>
  <p class="lede">Every remaining domain that needs an account — part {n} of
    {len(chunks)}. Sign up with the shared mailbox; the extension does the rest. Market,
    CAPTCHA flag and the full sign-up URL for each are in the spreadsheet.</p>
  <ul class="names3">{items}</ul>
</section>
""")
    return "".join(pages)


citations = cit_overview() + cit_list_pages()

# ============================================================ 13. mailbox
mailbox = f"""
<section class="page">
  {PH.format('How accounts are kept')}
  <h2 class="sec">One mailbox,<br>{T['accounts_total']} accounts</h2>
  <p class="lede">This is why the email account matters more than it sounds, and why the
    one we were sent has to be replaced before anything else starts.</p>

  <div class="mailflow">
    <div class="mf"><div class="mf-n">1</div><b>One catch-all mailbox</b>
      <span>Every address at the domain lands in one inbox.</span></div>
    <div class="mf-a">&rarr;</div>
    <div class="mf"><div class="mf-n">2</div><b>A unique alias per account</b>
      <span>acme-hotfrog@&hellip;, acme-tumblr@&hellip; — never the same address twice.</span></div>
    <div class="mf-a">&rarr;</div>
    <div class="mf"><div class="mf-n">3</div><b>The confirmation is read back</b>
      <span>The link is opened and the account is activated.</span></div>
    <div class="mf-a">&rarr;</div>
    <div class="mf"><div class="mf-n">4</div><b>Sealed in the vault</b>
      <span>Encrypted on the way in, never displayed again.</span></div>
  </div>

  <div class="inbox">
    <div class="ib-bar">Inbox &middot; accounts@clientdomain.com
      <span class="ib-count">4 unread</span></div>
    <div class="ib-row"><b>Hotfrog</b><i>Confirm your business listing</i>
      <em>acme-hotfrog@clientdomain.com</em><span class="ib-tag">citation</span></div>
    <div class="ib-row"><b>Tumblr</b><i>Verify your email address</i>
      <em>acme-tumblr@clientdomain.com</em><span class="ib-tag w2">web 2.0</span></div>
    <div class="ib-row"><b>Brownbook</b><i>Activate your account</i>
      <em>acme-brownbook@clientdomain.com</em><span class="ib-tag">citation</span></div>
    <div class="ib-row"><b>Substack</b><i>Finish setting up your publication</i>
      <em>acme-substack@clientdomain.com</em><span class="ib-tag w2">web 2.0</span></div>
  </div>

  <div class="two">
    <div class="card-dark">
      <div class="cd-h">Why aliases, not one shared address</div>
      <p>Platforms ban the "one email, many accounts" pattern outright — and one shared
        login means a single suspension takes every client offline at once, while handing
        the platform your whole client list. Aliases keep each account independent.</p>
    </div>
    <div class="card-tint">
      <div class="ct-h">What a working mailbox needs</div>
      <ul class="tick">
        <li><b>IMAP enabled</b>, with the host and port</li>
        <li><b>An app password</b> if it is Gmail — not the account password</li>
        <li><b>Catch-all routing</b> if it is your own domain</li>
        <li>Enough room that confirmation mail is not bounced</li>
      </ul>
    </div>
  </div>
</section>
"""

# ============================================================ 14. send back
send = f"""
<section class="page">
  {PH.format('Checklist')}
  <h2 class="sec">What to send back</h2>
  <p class="lede">Four items. Each switches on its own capability the moment it lands —
    nothing has to arrive together.</p>

  <div class="checks">
    <div class="chk"><span class="cb"></span><div><b>DataForSEO login and password</b>
      <em>One account, every client. Switches grid tracking, keyword volumes and backlink
        data onto your own billing instead of ours.</em></div></div>
    <div class="chk"><span class="cb"></span><div><b>A working email account</b>
      <em>IMAP host, username and password. Replaces the one sent recently, which does not
        authenticate. Nothing can be signed up for until this lands.</em></div></div>
    <div class="chk"><span class="cb"></span><div><b>Platform accounts, as you want them used</b>
      <em>{T['cit_signups']} citation directories and {T['web2_accounts']} Web 2.0 platforms —
        the full lists are in the accompanying spreadsheet, with sign-up links.</em></div></div>
    <div class="chk"><span class="cb"></span><div><b>Each client's business record</b>
      <em>Name, address, phone, hours, categories, description, logo and photos. Entered
        once; every submission is filled from it, so the details never drift.</em></div></div>
  </div>

  <div class="card-dark wide">
    <div class="cd-h">How to send credentials</div>
    <p>Never by email or chat. Use a one-time secret link, or type them straight into the
      dashboard — anything entered there is encrypted on arrival and is never shown again,
      not to us and not in any log.</p>
  </div>
  <div class="endnote">Platform counts were read from the running registry on
    12&nbsp;September&nbsp;2026. Where something has not been measured, this document says
    so rather than showing a zero.</div>
</section>
"""

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{
 --maroon:#6E1423;--maroon-2:#8C1D2E;--maroon-deep:#3F0E18;--rose:#B85C6B;
 --rose-soft:#D89AA3;--blush:#F8ECEE;--blush-2:#F1DADE;--line:#E8D2D7;
 --ink:#241015;--white:#fff;
}
@page{size:A4;margin:0}
html,body{background:#fff}
body{font-family:'Bricolage Grotesque',system-ui,sans-serif;color:var(--ink);
 -webkit-print-color-adjust:exact;print-color-adjust:exact;font-variation-settings:'wght' 400}
.page{width:210mm;height:296mm;padding:15mm 15mm;background:#fff;overflow:hidden;
 page-break-after:always;position:relative;display:flex;flex-direction:column}
.ph{display:flex;justify-content:space-between;font-size:11.5px;font-weight:600;
 color:var(--rose);letter-spacing:.06em;text-transform:uppercase;
 border-bottom:1px solid var(--line);padding-bottom:7px;margin-bottom:11mm}
.sec{font-size:43px;font-weight:800;letter-spacing:-.025em;line-height:1.02;
 color:var(--maroon-deep);margin-bottom:7px}
.lede{font-size:15px;font-weight:420;line-height:1.5;color:#5C4249;max-width:152mm;
 margin-bottom:8mm}
.sub{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.09em;
 color:var(--maroon-2);margin:0 0 4mm;padding-bottom:4px;border-bottom:2px solid var(--blush-2)}
.sub2{margin-top:7mm}

/* cover */
.cover{background:var(--maroon-deep);color:#fff;padding:20mm 17mm;justify-content:space-between}
.cov-mid{margin-top:-26mm}
.cov-eyebrow{font-size:13px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;
 color:var(--rose-soft)}
.cov-rule{width:44mm;height:3px;background:var(--rose);margin-top:7mm}
.cov-title{font-size:88px;font-weight:800;line-height:.94;letter-spacing:-.035em}
.cov-sub{font-size:17px;font-weight:420;line-height:1.45;color:#EBD2D7;max-width:120mm;
 margin-top:8mm}
.cov-stats{display:flex;gap:9mm;border-top:1px solid rgba(255,255,255,.2);padding-top:7mm}
.cov-stat b{display:block;font-size:46px;font-weight:800;letter-spacing:-.03em;line-height:1}
.cov-stat span{font-size:12.5px;font-weight:500;color:var(--rose-soft)}
.cov-note{font-size:11.5px;color:#B98C95;margin-top:6mm;line-height:1.45;max-width:135mm}

/* flow */
.flow{display:flex;flex-direction:column;gap:3.2mm;margin-bottom:8mm}
.flow-step{display:flex;gap:5mm;align-items:center;border:1px solid var(--line);
 border-left:4px solid var(--maroon-2);border-radius:8px;padding:4.2mm 5mm;background:#fff}
.flow-step.done{border-left-color:#2E7D5B;background:var(--blush)}
.fs-n{font-size:25px;font-weight:800;color:var(--maroon-2);min-width:11mm;text-align:center}
.flow-step.done .fs-n{color:#2E7D5B}
.fs-b b{display:block;font-size:17px;font-weight:800;color:var(--maroon-deep)}
.fs-b span{font-size:14px;font-weight:420;color:#5C4249;line-height:1.4}

/* cards */
.two{display:grid;grid-template-columns:1fr 1fr;gap:5mm;margin-top:auto}
.card-dark{background:var(--maroon-deep);color:#fff;border-radius:10px;padding:6mm}
.card-dark.wide{margin-top:7mm}
.cd-h{font-size:17px;font-weight:800;margin-bottom:3.5mm}
.card-dark p{font-size:14px;font-weight:420;line-height:1.5;color:#EBD2D7}
.card-tint{background:var(--blush);border:1px solid var(--line);border-radius:10px;padding:6mm}
.card-tint.wide{margin-top:6mm}
.ct-h{font-size:17px;font-weight:800;color:var(--maroon-deep);margin-bottom:3.5mm}
.ct-f{font-size:11.5px;color:var(--rose);margin-top:3mm;font-weight:600;line-height:1.4}
.plain{font-size:13px;font-weight:450;line-height:1.55;color:#4A2F36}
.tick{list-style:none}
.tick li{font-size:14px;font-weight:420;line-height:1.42;color:#4A2F36;padding-left:7mm;
 position:relative;margin-bottom:2.8mm}
.tick li:before{content:"";position:absolute;left:0;top:6px;width:3.4mm;height:3.4mm;
 border-radius:50%;background:var(--maroon-2)}

/* needed cards */
.needs{display:flex;flex-direction:column;gap:6mm}
.needcard{border:1px solid var(--line);border-left:5px solid var(--maroon-2);
 border-radius:10px;background:var(--blush);padding:6mm 6.5mm}
.nc-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:5mm}
.nc-name{font-size:30px;font-weight:800;color:var(--maroon-deep);letter-spacing:-.02em;
 line-height:1.05}
.nc-area{font-size:12.5px;font-weight:700;color:var(--rose);text-transform:uppercase;
 letter-spacing:.07em;margin-top:1.6mm}
.nc-grid{display:grid;grid-template-columns:1fr 1fr;gap:4.4mm 6mm}
.nc-grid b{display:block;font-size:11.5px;font-weight:800;text-transform:uppercase;
 letter-spacing:.07em;color:var(--maroon-2);margin-bottom:1.4mm}
.nc-grid span{font-size:13.5px;font-weight:430;line-height:1.45;color:#4A2F36}
.nc-key{font-family:ui-monospace,monospace;font-size:11.5px;font-weight:700;
 color:var(--maroon-2);margin-top:5mm;padding-top:3.4mm;border-top:1px solid var(--line);
 word-break:break-all}

/* api grid */
.agrid{display:grid;grid-template-columns:1fr 1fr;gap:3.4mm}
.acard{border:1px solid var(--line);border-radius:8px;padding:4.2mm 4.6mm;background:#fff}
.acard.ok{border-left:4px solid #2E7D5B}
.ac-top{display:flex;justify-content:space-between;align-items:center;gap:3mm;margin-bottom:2mm}
.ac-top b{font-size:16px;font-weight:800;color:var(--maroon-deep)}
.pill{font-size:9.5px;font-weight:800;text-transform:uppercase;letter-spacing:.07em;
 padding:1.4mm 2.6mm;border-radius:99px;white-space:nowrap}
.pok{background:#DFF0E7;color:#1E5E43}
.pneed{background:var(--maroon-2);color:#fff}
.ac-p{font-size:13px;font-weight:420;line-height:1.4;color:#5C4249}
.ac-k{font-size:10.5px;font-weight:700;color:var(--maroon-2);margin-top:2.4mm;
 font-family:ui-monospace,monospace;word-break:break-all}

/* consequence / removed table */
.ctable{display:flex;flex-direction:column;gap:1.6mm;margin-bottom:auto}
.crow{display:grid;grid-template-columns:58mm 8mm 1fr;align-items:center;gap:2mm;
 border-bottom:1px solid var(--line);padding:2.9mm 0}
.cr-n{font-size:14.5px;font-weight:800;color:var(--maroon-deep)}
.cr-arrow{color:var(--rose);font-weight:800;font-size:16px}
.cr-c{font-size:13px;font-weight:420;color:#5C4249;line-height:1.4}

/* browser mockup */
.browser{border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-bottom:8mm;
 box-shadow:0 2mm 6mm rgba(62,14,24,.08)}
.br-bar{background:var(--blush-2);padding:2.6mm 4mm;display:flex;align-items:center;gap:2mm}
.dot{width:2.6mm;height:2.6mm;border-radius:50%;display:block}
.dot.r{background:#D4707F}.dot.y{background:#E0B070}.dot.g{background:#7FB894}
.br-url{flex:1;background:#fff;border:1px solid var(--line);border-radius:99px;
 font-size:10.5px;font-weight:600;color:#7A5A61;padding:1.4mm 4mm;margin-left:2mm}
.br-body{display:grid;grid-template-columns:1fr 58mm;background:#fff}
.br-page{padding:5mm;border-right:1px solid var(--line)}
.skel{background:var(--blush-2);border-radius:3px;margin-bottom:4mm}
.w60{width:60%}.h18{height:5mm}
.field{border:1px solid var(--line);border-radius:5px;padding:2.4mm 3mm;margin-bottom:2.6mm;
 background:#FCF7F8}
.field i{display:block;font-size:9.5px;font-weight:700;color:var(--rose);font-style:normal;
 text-transform:uppercase;letter-spacing:.06em}
.field b{font-size:12.5px;font-weight:700;color:var(--maroon-deep)}
.field.empty{border-style:dashed;border-color:var(--rose-soft)}
.field b.wait{color:var(--rose);font-weight:600;font-style:italic}
.submit{background:var(--maroon-2);color:#fff;font-size:12px;font-weight:800;text-align:center;
 border-radius:5px;padding:2.8mm;margin-top:4mm}
.br-panel{padding:4.4mm;background:var(--maroon-deep);color:#fff}
.bp-h{font-size:13px;font-weight:800;letter-spacing:.1em;color:var(--rose-soft);
 margin-bottom:3mm}
.bp-tabs{display:flex;gap:1.6mm;margin-bottom:3.4mm}
.bp-tabs span{font-size:10px;font-weight:700;padding:1.4mm 2.6mm;border-radius:99px;
 background:rgba(255,255,255,.12);color:#E8CDD2}
.bp-tabs span.on{background:var(--rose);color:#fff}
.bp-task{font-size:13px;font-weight:800;margin-bottom:3mm}
.bp-task em{display:block;font-size:10px;font-weight:500;font-style:normal;
 color:var(--rose-soft);margin-top:.8mm}
.bp-row{font-size:10.5px;font-weight:600;padding:1.8mm 2.4mm;border-radius:4px;
 margin-bottom:1.6mm;background:rgba(255,255,255,.08);color:#EBD2D7}
.bp-row.ok{border-left:2.4px solid #7FB894}
.bp-row.work{border-left:2.4px solid #E0B070;font-style:italic}
.bp-cta{margin-top:3.4mm;background:var(--rose);border-radius:5px;text-align:center;
 font-size:11px;font-weight:800;padding:2.4mm}

/* citation flow */
.cflow{display:flex;align-items:stretch;gap:1.6mm;margin-bottom:auto}
.cf{flex:1;border:1px solid var(--line);border-radius:8px;padding:4mm 3.2mm;background:var(--blush)}
.cf-n{width:7mm;height:7mm;border-radius:50%;background:var(--maroon-deep);color:#fff;
 font-size:12.5px;font-weight:800;display:flex;align-items:center;justify-content:center;
 margin-bottom:2.4mm}
.cf b{font-size:12.5px;font-weight:800;color:var(--maroon-deep);display:block;margin-bottom:1.4mm}
.cf span{font-size:10.5px;font-weight:420;line-height:1.35;color:#5C4249}
.cf-a{align-self:center;color:var(--rose-soft);font-weight:800;font-size:14px}

/* vs */
.vs{display:grid;grid-template-columns:1fr 1fr;gap:5mm;margin-bottom:8mm}
.vs-col{border-radius:10px;padding:6mm}
.vs-col.good{background:var(--maroon-deep);color:#fff}
.vs-col.good .tick li{color:#EBD2D7}
.vs-col.good .tick li:before{background:var(--rose-soft)}
.vs-col.warn{background:var(--blush);border:1px solid var(--line)}
.vs-h{font-size:17px;font-weight:800;margin-bottom:4mm}
.vs-col.warn .vs-h{color:var(--maroon-deep)}

.covbars{display:flex;flex-direction:column;gap:3mm;margin-bottom:auto}
.cbar{display:grid;grid-template-columns:52mm 1fr 22mm;align-items:center;gap:3mm}
.cbar span{font-size:13px;font-weight:700;color:#4A2F36}
.cbar i{height:6mm;background:var(--maroon-2);border-radius:3px;display:block;min-width:1.4mm}
.cbar.alt i{background:var(--rose-soft)}
.cbar em{font-size:13px;font-weight:800;color:var(--maroon);font-style:normal;text-align:right}

.stats4{display:grid;grid-template-columns:repeat(4,1fr);gap:3.4mm;margin-bottom:7mm}
.st{background:var(--blush);border:1px solid var(--line);border-radius:8px;padding:4.2mm}
.st b{display:block;font-size:44px;font-weight:800;color:var(--maroon);line-height:1;
 letter-spacing:-.03em}
.st span{font-size:12px;font-weight:500;color:#5C4249;display:block;margin-top:1.6mm;
 line-height:1.3}

.bars{display:flex;flex-direction:column;gap:3mm}
.bar{display:grid;grid-template-columns:20mm 1fr 8mm;align-items:center;gap:2.4mm}
.bar span{font-size:12.5px;font-weight:700;color:#4A2F36}
.bar i{height:5.4mm;background:var(--maroon-2);border-radius:3px;display:block;min-width:2mm}
.bar em{font-size:13px;font-weight:800;color:var(--maroon);font-style:normal;text-align:right}

/* dedupe rows */
.dedupe{display:grid;grid-template-columns:1fr 1fr;gap:2.4mm 4mm;margin-bottom:7mm}
.dd{display:flex;align-items:center;gap:1.2mm;overflow:hidden;border:1px solid var(--line);border-radius:6px;
 padding:2.4mm 3mm;background:#fff}
.dd b{font-size:11px;font-weight:800;color:var(--maroon-deep);min-width:25mm;white-space:nowrap}
.dd span{font-size:8px;font-weight:800;letter-spacing:.04em;color:#fff;
 background:var(--rose);border-radius:99px;padding:.8mm 1.4mm;white-space:nowrap}
.dd em{margin-left:auto;font-size:10px;font-weight:800;color:var(--maroon-2);font-style:normal;
 white-space:nowrap;padding-left:1.5mm}

/* platform card grid */
.pgrid4{display:grid;grid-template-columns:repeat(4,1fr);gap:2.6mm}
.pcard2{border:1px solid var(--line);border-left:3px solid var(--rose);border-radius:6px;
 padding:2.8mm 3mm;background:#fff;min-height:0}
.pcard2.core{border-left-color:var(--maroon-2);background:var(--blush)}
.pcard2.agg{border-left-color:#9BA89F;background:#F4F6F4;border-style:dashed}
.pcard2 b{display:block;font-size:11.5px;font-weight:800;color:var(--maroon-deep);
 line-height:1.2}
.pcard2 span{display:block;font-size:9px;font-weight:500;color:var(--rose);margin-top:1mm;
 word-break:break-all;line-height:1.2}

/* long name lists */
.names3{list-style:none;column-count:3;column-gap:6mm;margin-bottom:auto}
.names3 li{break-inside:avoid;padding:1.15mm 0;border-bottom:1px solid var(--blush-2);
 line-height:1.25}
.names3 li b{font-size:10px;font-weight:800;color:var(--maroon-deep)}
.names3 li em{font-size:8px;font-weight:500;color:var(--rose);font-style:normal;
 word-break:break-all}

/* mailbox */
.mailflow{display:flex;align-items:stretch;gap:2mm;margin-bottom:9mm}
.mf{flex:1;border:1px solid var(--line);border-radius:8px;padding:4.4mm 3.6mm;
 background:var(--blush)}
.mf-n{width:7mm;height:7mm;border-radius:50%;background:var(--maroon-deep);color:#fff;
 font-size:12.5px;font-weight:800;display:flex;align-items:center;justify-content:center;
 margin-bottom:2.6mm}
.mf b{font-size:13.5px;font-weight:800;color:var(--maroon-deep);display:block;
 margin-bottom:1.6mm}
.mf span{font-size:11.5px;font-weight:420;line-height:1.35;color:#5C4249}
.mf-a{align-self:center;color:var(--rose-soft);font-weight:800;font-size:14px}

/* inbox mockup */
.inbox{border:1px solid var(--line);border-radius:9px;overflow:hidden;margin-bottom:8mm;
 box-shadow:0 2mm 5mm rgba(62,14,24,.07)}
.ib-bar{background:var(--maroon-deep);color:#fff;font-size:12px;font-weight:800;
 padding:3mm 4.4mm;display:flex;align-items:center}
.ib-count{margin-left:auto;font-size:9.5px;font-weight:700;background:var(--rose);
 border-radius:99px;padding:1mm 2.4mm}
.ib-row{display:flex;align-items:center;gap:3mm;padding:3.2mm 4.4mm;
 border-bottom:1px solid var(--line);background:#fff}
.ib-row:last-child{border-bottom:0}
.ib-row:nth-child(odd){background:#FDF9FA}
.ib-row b{font-size:12.5px;font-weight:800;color:var(--maroon-deep);min-width:26mm}
.ib-row i{font-size:12px;font-weight:450;color:#4A2F36;font-style:normal;min-width:62mm}
.ib-row em{font-size:10px;font-weight:600;color:var(--rose);font-style:normal;
 margin-left:auto;white-space:nowrap}
.ib-tag{font-size:8px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;
 background:var(--blush-2);color:var(--maroon-2);border-radius:99px;padding:1mm 2mm;
 white-space:nowrap;min-width:16mm;text-align:center}
.ib-tag.w2{background:var(--maroon-2);color:#fff}

/* checklist */
.checks{display:flex;flex-direction:column;gap:3.4mm;margin-bottom:auto}
.chk{display:flex;gap:4.4mm;align-items:flex-start;border:1px solid var(--line);
 border-radius:8px;padding:4.6mm 5mm}
.cb{width:6mm;height:6mm;border:2.2px solid var(--maroon-2);border-radius:3px;flex:0 0 auto;
 margin-top:1mm}
.chk b{font-size:16.5px;font-weight:800;color:var(--maroon-deep);display:block}
.chk em{font-size:13px;font-weight:420;color:#5C4249;font-style:normal;display:block;
 margin-top:1.2mm;line-height:1.4}
.endnote{font-size:11.5px;color:var(--rose);margin-top:6mm;font-weight:600;
 border-top:1px solid var(--line);padding-top:4mm;line-height:1.4}
"""

html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>AIOS Access &amp; Accounts (rev 2)</title>
<style>{FONTCSS}</style>
<style>{CSS}</style>
</head><body>
{cover}{glance}{needed}{installed}{removed}{extension}{vs}{web2a}{web2b}{citations}{mailbox}{send}
</body></html>
"""

OUT.write_text(html, encoding="utf-8")
print("WROTE", OUT, len(html), "bytes")
print("pages", html.count('class="page'))
