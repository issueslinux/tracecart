"""Isolated, prominently labeled fictional-store / Sandbox demo HTML views."""
from html import escape
from core import CONSENT_TEXT
from demo_purchase import (DEMO_SKU,DEMO_MERCHANT,DEMO_INTERMEDIARY,
                           mock_merchant_item)


def h(x):
    return escape(str(x),quote=True)


def store_html(csrf):
    item=mock_merchant_item(DEMO_SKU)
    return '''<section><div class="tag">FICTIONAL STORE · INTERACTIVE DEMO</div>
      <h2>Demo Retailer</h2><p>Retailer, inventory and storefront are
      <b>entirely simulated</b>. No third-party retailer participates.
      This fictional retailer does not accept PayPal directly.</p>
      <div class="tag">SAMPLE PRODUCT</div><h2>{title}</h2>
      <p class="total">{price} USD</p>
      <p>Quantity: 1 · Illustrative inventory. The fictional retailer
      accepts demo cards/bank transfers (not actually processed).</p>
      <form method="post" action="/demo/store/add">{csrf}
       <input type="hidden" name="sku" value="{sku}">
       <button type="submit">Add to cart</button>
      </form><p class="muted">One click starts automatic research and an AI
      risk review. No URL to paste and no Analyze button.</p></section>
      <section><h2>What happens after this click?</h2>
      <p>TraceCart creates the evidence graph, local AI writes a risk plan,
      and the buyer reviews a quote paid only to
      <b>{intermediary}</b> in PayPal Sandbox. The fictional shop
      can acknowledge a simulated order after verified Sandbox buyer approval.
      <b>There is no actual merchandise purchase, capture or delivery.</b></p>
      </section>'''.format(title=h(item['title']),price=h(item['price']),
                          sku=DEMO_SKU,csrf=csrf,intermediary=h(DEMO_INTERMEDIARY))


def order_html(job_id,demo,research,quote,csrf):
    """Return rendered page body and optional seconds to refresh automatically."""
    status=research['state'];ai=demo['ai_status'];item=research['item']
    body='''<section><div class="tag">CART ADD EVENT ACCEPTED · NO URL PASTED</div>
      <h2>{title}</h2><p><b>{merchant}</b> · Fictional item and store.</p>
      <p>The user reached TraceCart by clicking <b>Add to cart</b>.
      Research and AI start automatically; payment has not been authorized.</p>
      <p>Research: <code>{state}</code> · AI: <code>{ai}</code></p>
      <p><a class="btn" href="/cart/status/{job_id}">Open live research graph</a>
      <a class="btn" href="/demo/store">Demo storefront</a></p>
      </section>'''.format(title=h(item['title']),merchant=h(DEMO_MERCHANT),
            state=h(status),ai=h(ai),job_id=h(job_id))
    if status=='FAILED':
        return body+'''<section class="error">Research failed; PayPal payment
          is blocked. No order or real purchase occurred.</section>''',None
    if status!='READY' or ai in ('WAITING_FOR_RESEARCH','AI_RUNNING'):
        return body+'''<section><h2>Automatic research and AI plan in progress</h2>
          <p>This page refreshes automatically. No additional click is needed.
          The fictional store claims are not checkout-verified.</p></section>''',2
    if ai=='AI_UNAVAILABLE':
        return body+'''<section class="error"><h2>Local AI unavailable</h2>
          <p>Qwen did not supply an acceptable risk plan. No fabricated AI output
          will be shown and checkout cannot start. Configure local Ollama/Qwen
          for the live hackathon demonstration.</p></section>''',None
    note=demo['ai_result'] or {}
    checks=''.join('<li>{}</li>'.format(h(x))
                   for x in note.get('buyer_checks',[]))
    body+='''<section><div class="tag">AI RISK PLAN · NONAUTHORITATIVE</div>
      <h2>Research-informed purchase plan</h2>
      <p><b>Local model:</b> {model} ·
      <b>AI advisory risk:</b> {risk} · <b>Mandatory policy risk:</b>
      FICTIONAL STORE, NO INDEPENDENT CHECKOUT.</p>
      <p>{note}</p><ul>{checks}</ul>
      <p class="warning">The AI risk level is advisory only; it never sets
      an amount, authorizes payment or converts unknown claims into facts.
      Product, inventory, shipping and store checkout are not verified.</p>
      </section>'''.format(model=h(note.get('model','Qwen')),
                          risk=h(note.get('risk_level','UNKNOWN')),
                          note=h(note.get('risk_note','')),checks=checks)
    body+='''<section><div class="tag">SERVER-CONTROLLED SANDBOX QUOTE</div>
      <h2>Intended demo intermediary: {intermediary}</h2>
      <p><b>NOT payable to {merchant}.</b> The actual PayPal Sandbox merchant
      is the business account attached to the configured REST app; this demo
      label is not verification of that account's legal identity.
      The fictional intermediary would
      pay a fictional merchant through another payment method in a real
      brokerage model. No such purchase is executed by this demo.</p>
      <p>Fixed SKU: <code>{sku}</code> · Quantity: 1</p>
      <p class="total">{amount} USD</p><p>PayPal state: <code>{state}</code></p>
      '''.format(intermediary=h(DEMO_INTERMEDIARY),merchant=h(DEMO_MERCHANT),
                 sku=h(demo['sku']),amount=h(quote['total']),state=h(quote['state']))
    if quote['state']=='QUOTED':
        body+='''<p>No PayPal API order exists yet. Explicit buyer consent
        and an exact amount confirmation are mandatory.</p>
        <form method="post" action="/demo/order/{job_id}/approve">{csrf}
        <label>Confirm exactly {amount} USD
          <input type="text" name="expected_total" required></label>
        <label>Type <code>{consent}</code>
          <input type="text" name="consent" required></label>
        <button>Approve amount and continue with PayPal Sandbox</button>
        </form>'''.format(job_id=h(job_id),csrf=csrf,
                         amount=h(quote['total']),consent=h(CONSENT_TEXT))
    elif quote['state']=='APPROVED':
        body+='''<p class="warning">Buyer consent is recorded, but a Sandbox
        order has not been created. Authorized Sandbox credentials are
        required. No real funds can be moved by this app.</p>
        <form method="post" action="/demo/order/{job_id}/paypal">{csrf}
         <button>Continue to PayPal Sandbox</button></form>'''.format(
            job_id=h(job_id),csrf=csrf)
    elif quote['state']=='PAYER_ACTION_REQUIRED':
        body+='''<p>Actual PayPal Sandbox order: <code>{order_id}</code>.
        Status: buyer action required. <b>No capture implemented.</b></p>
        <a class="btn" href="{url}" target="_blank" rel="noopener noreferrer">
        Open PayPal Sandbox for buyer approval</a>
        <p>When the Sandbox buyer approves, check the order using the
        read-only API. Only actual status APPROVED with the exact amount
        can cause the simulated store to acknowledge it.</p>
        <form method="post" action="/demo/order/{job_id}/verify">{csrf}
         <button>Verify buyer approval and update demo order</button></form>
        '''.format(order_id=h(quote['paypal_id']),url=h(quote['approval_url']),
                   job_id=h(job_id),csrf=csrf)
    else:
        body+='''<p class="warning">Sandbox order creation is uncertain or
        failed. No automatic payment retry or merchant acceptance is allowed.
        A read-only manual reconciliation may be needed.</p>'''
    body+='</section>'
    if demo['simulated_state']=='SIMULATED_ACCEPTED':
        body+='''<section><div class="tag">DEMO SHOP · SIMULATED ACCEPTANCE</div>
          <h2>Order accepted in simulation</h2>
          <p>Simulated reference: <code>{ref}</code></p>
          <p>PayPal Sandbox confirmed an <b>APPROVED</b> order with the
          server-controlled amount. The fictional store updated its
          simulated order status. <b>No payment capture, real merchant order,
          goods delivery or payout occurred.</b></p></section>'''.format(
            ref=h(demo['simulated_order_id']))
    return body,None
