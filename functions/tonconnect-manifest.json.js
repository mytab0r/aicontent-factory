// TonConnect wallet manifest — required static JSON for TON Connect wallets to display app info.
// https://docs.ton.org/develop/dapps/ton-connect/manifest
export async function onRequestGet() {
  return new Response(JSON.stringify({
    url: 'https://pay.pxbt.app',
    name: 'PXBT Pay',
    iconUrl: 'https://pay.pxbt.app/favicon.ico',
  }), { headers: { 'content-type': 'application/json' } });
}
