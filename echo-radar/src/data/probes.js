export const ACTIVE_PROBES = [
  { kind: 'keyword', q: 'испорченный заказ', pf: ['instagram','tiktok'], interval: '4 мин', trend: 'up',   last: '12 сек', hot: true,  mentions: 23 },
  { kind: 'hashtag', q: '#папапицца',        pf: ['instagram','tiktok'], interval: '8 мин', trend: 'flat', last: '1 мин',  hot: false, mentions: 64 },
  { kind: 'mention', q: '@papapizza',        pf: ['instagram','tiktok'], interval: '6 мин', trend: 'flat', last: '40 сек', hot: false, mentions: 41 },
  { kind: 'keyword', q: 'холодная пицца',    pf: ['instagram','tiktok'], interval: '12 мин',trend: 'down', last: '3 мин',  hot: false, mentions: 9 },
];

export const AI_SUGGEST = ['вернули деньги', '#отзывброкен', 'курьер опоздал', 'заказ не привезли', 'долгая доставка'];

export const KIND = { keyword: 'Ключевое слово', hashtag: 'Хэштег', mention: 'Упоминание' };
