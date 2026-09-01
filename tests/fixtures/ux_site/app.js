/* Fixture behaviours, each one a defect the agent is expected to find.
   Nothing here is random: a test that measures a random delay measures
   nothing. */

const SEARCH_DELAY = 620;   // well past the 200ms "instant" threshold
const CART_DELAY   = 900;   // slow, and with no feedback while it works

function $(id) { return document.getElementById(id); }

/* Menu: opens on click, fast. This is the control that should PASS. */
const menu = $('menu');
if (menu) {
  menu.addEventListener('click', () => {
    const dd = $('dropdown');
    const open = menu.getAttribute('aria-expanded') === 'true';
    menu.setAttribute('aria-expanded', String(!open));
    dd.hidden = open;
  });
}

/* Search: suggestions arrive late, and nothing indicates they are coming. */
let searchTimer = null;
const q = $('q');
if (q) {
  q.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const ul = $('suggest');
      ul.hidden = false;
      ul.innerHTML = ['Copper Kettle', 'Linen Throw', 'Oak Stool']
        .map(s => `<li>${s}</li>`).join('');
    }, SEARCH_DELAY);
  });
}

function doSearch(e) {
  e.preventDefault();
  const box = $('results');
  setTimeout(() => {
    box.innerHTML = '<h3>Results</h3><ul><li><a href="/product.html?sku=1">' +
                    'Copper Kettle</a></li></ul>';
  }, SEARCH_DELAY);
  return false;
}

/* Add to cart: the network work is simulated, and CRUCIALLY nothing on
   screen changes until it finishes. That is the "silent action" finding. */
function addToCart() {
  setTimeout(() => {
    const c = $('count');
    if (c) c.textContent = String(Number(c.textContent || '0') + 1);
    const note = $('cartnote');
    if (note) note.textContent = 'Added to your cart.';
  }, CART_DELAY);
}

/* A late banner that pushes the page down — a layout shift after paint. */
window.addEventListener('load', () => {
  setTimeout(() => {
    const b = document.createElement('div');
    b.className = 'banner';
    b.textContent = 'Free delivery this week only.';
    const main = document.querySelector('main');
    if (main) main.insertBefore(b, main.firstChild);
  }, 700);
});

/* #dead has no listener. Pressing it does nothing, on purpose. */
