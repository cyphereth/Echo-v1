export const BRAND = { name: 'Папа Пицца', handle: '@papapizza', monogram: 'ПП', probes: 4 };

export function sevTone(s) {
  if (s >= 75) return { key: 'critical', color: '#FF4D5E', bright: '#FF7A87', ghost: 'rgba(255,77,94,.14)', line: 'rgba(255,77,94,.38)', label: 'Залетает' };
  if (s >= 45) return { key: 'rising',   color: '#FFB23E', bright: '#FFC871', ghost: 'rgba(255,178,62,.14)', line: 'rgba(255,178,62,.36)', label: 'Растёт' };
  return { key: 'calm', color: '#2BB3C7', bright: '#57D2E2', ghost: 'rgba(43,179,199,.12)', line: 'rgba(43,179,199,.32)', label: 'Под контролем' };
}

export const PHASE = {
  rising:    { label: 'растёт',   icon: 'trendingUp',   color: '#FFC871' },
  declining: { label: 'затухает', icon: 'trendingDown', color: '#7E91A6' },
  unknown:   { label: 'не ясно',  icon: 'activity',     color: '#7E91A6' },
};

export const TONE = {
  negative: { label: 'Негатив',    color: '#FF7A87' },
  neutral:  { label: 'Нейтрально', color: '#97A9BE' },
  positive: { label: 'Позитив',    color: '#34D8A0' },
};

export const INITIAL_DATA = [
  {
    id: 'm1', platform: 'tiktok', author: 'user123', followers: 12400, ago: '14 мин',
    text: 'Заказала ужин, привезли через 2 часа и всё холодное. Это они так со всеми? Снимаю на видео 👇',
    severity: 87, phase: 'rising', tone: 'negative', confidence: 0.94, category: 'viral_negative',
    lane: 'PR', hot: true, views: [800, 1200, 2100, 3400, 4800], peakViews: '4.8k', rate: '+340/мин',
    draft: 'Здравствуйте, простите за испорченный ужин — это не норма. Пришлите номер заказа в личные сообщения, вернём деньги и разберёмся с курьером сегодня.',
    status: 'new',
  },
  {
    id: 'm2', platform: 'instagram', author: 'kirill.reviews', followers: 3200, ago: '32 мин',
    text: 'Опять опоздали на час, третий заказ подряд. Холодная пицца, как обычно. Больше не закажу.',
    severity: 64, phase: 'rising', tone: 'negative', confidence: 0.88, category: 'complaint',
    lane: 'PR', hot: true, views: [200, 400, 700, 1100, 1500], peakViews: '1.5k', rate: '+90/мин',
    draft: 'Кирилл, это наша вина и так быть не должно. Напишите номер последнего заказа — компенсируем доставку и передадим в курьерскую службу вашего района.',
    status: 'new',
  },
  {
    id: 'm5', platform: 'instagram', author: 'an_user_77', followers: 120, ago: '3 ч',
    text: 'ну отличная у вас доставка, как всегда 🙃 спасибо что испортили вечер',
    severity: 33, phase: 'unknown', tone: 'negative', confidence: 0.41, category: 'complaint',
    lane: 'none', hot: false, views: [40, 60, 75, 80, 84], peakViews: '84', rate: '+2/мин',
    draft: null,
    status: 'human',
  },
  {
    id: 'm6', platform: 'tiktok', author: 'foodcritic.msk', followers: 21000, ago: '5 ч',
    text: 'Разбирали доставки города. У этих — то густо, то пусто. Сегодня вот привезли вовремя, удивили.',
    severity: 41, phase: 'declining', tone: 'neutral', confidence: 0.82, category: 'neutral',
    lane: 'PR', hot: false, views: [3000, 5200, 5000, 4600, 4200], peakViews: '5.2k ↓', rate: '−110/мин',
    draft: 'Спасибо за разбор! Работаем над стабильностью — если попадёте на сбой, пишите в директ, разберём конкретный заказ.',
    status: 'sent',
  },
  {
    id: 'm3', platform: 'instagram', author: 'olya_moscow', followers: 880, ago: '1 ч',
    text: 'Спасибо! Курьер был супервежливый и привёз раньше срока, пицца горячая 🍕 редкость сейчас',
    opportunity: 71, severity: 18, phase: 'rising', tone: 'positive', confidence: 0.91, category: 'positive',
    lane: 'SMM', hot: false, views: [120, 240, 360, 500, 640], peakViews: '640', rate: '+30/мин',
    draft: 'Оля, спасибо на добром слове! Передали курьеру — ему будет приятно. Можно репостнуть ваш отзыв в наши истории?',
    status: 'new',
  },
  {
    id: 'm4', platform: 'tiktok', author: 'prank.memes', followers: 45000, ago: '2 ч',
    text: 'когда заказал пиццу и она приехала быстрее чем бывшая ответила на сообщение 💀 #папапицца',
    severity: 58, phase: 'rising', tone: 'positive', confidence: 0.79, category: 'humor',
    lane: 'SMM', hot: true, views: [1200, 3000, 5800, 9000, 13000], peakViews: '13k', rate: '+600/мин',
    humor: true,
    draft: 'Главное — приоритеты у человека на месте 🍕 (ответ юмористический — публикуется только вручную SMM)',
    status: 'new',
  },
  {
    id: 'm7', platform: 'instagram', author: 'lena.himki', followers: 540, ago: '6 ч',
    text: 'А вы в Химки доставляете? И до скольки работает кухня в выходные?',
    severity: 22, phase: 'unknown', tone: 'neutral', confidence: 0.9, category: 'neutral',
    lane: 'SMM', hot: false, views: [60, 90, 110, 120, 128], peakViews: '128', rate: '+4/мин',
    draft: 'Да, Химки в зоне доставки! По выходным кухня работает до 23:30. Адрес подскажем точное время — напишите район в директ.',
    status: 'new',
  },
];
