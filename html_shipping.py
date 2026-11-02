"""Language-neutral, product-scoped shipping microdata evidence."""
from html.parser import HTMLParser
from structured_shipping import shipping_claims

class ShippingMicrodata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.details = []
        self.invalid = False
        self.product_count = 0
        self.offer_count = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        kind = (a.get('itemtype') or '').lower().rstrip('/').rsplit('/', 1)[-1]
        parent = self.stack[-1][1] if self.stack else None
        # Neutral layout wrappers may appear between semantic nodes.
        semantic_parent = next((context for _, context in reversed(self.stack) if context), None)
        context = None
        if 'itemscope' in a:
            if kind == 'product' and semantic_parent is None:
                context = 'product'
                self.product_count += 1
            elif kind == 'offer' and a.get('itemprop') == 'offers' and semantic_parent == 'product':
                context = 'offer'
                self.offer_count += 1
            elif kind == 'offershippingdetails' and a.get('itemprop') == 'shippingDetails' and semantic_parent == 'offer':
                context = 'shipping'
                self.details.append({'shippingDestination': {}, 'shippingRate': {}})
            elif kind == 'definedregion' and a.get('itemprop') == 'shippingDestination' and semantic_parent == 'shipping':
                context = 'destination'
            elif kind == 'monetaryamount' and a.get('itemprop') == 'shippingRate' and semantic_parent == 'shipping':
                context = 'rate'
        else:
            context = parent
        if self.details and context in ('destination', 'rate'):
            prop = a.get('itemprop')
            value = a.get('content')
            if value is not None and ((context == 'destination' and prop == 'addressCountry') or (context == 'rate' and prop in ('value', 'currency'))):
                target = self.details[-1]['shippingDestination' if context == 'destination' else 'shippingRate']
                if prop in target:
                    self.invalid = True
                else:
                    target[prop] = value[:80]
        if tag not in ('meta', 'link', 'input', 'br', 'img', 'hr', 'source', 'wbr'):
            self.stack.append((tag, context))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

def html_shipping_claims(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    if not isinstance(raw, str) or len(raw) > 1200000:
        return {}
    parser = ShippingMicrodata()
    parser.feed(raw)
    return {} if parser.invalid or parser.product_count != 1 or parser.offer_count != 1 else shipping_claims({'shippingDetails': parser.details})
