// Mock data — realistic Russian social media content for Echo demo

export const BRAND = {
  id: 1,
  name: 'PapaPizza',
  niche: 'доставка еды',
  competitors: ['DoDo Pizza', 'Dominos', 'Pizza Hut'],
  platforms: ['instagram', 'tiktok', 'telegram'],
};

const neg = (text) => ({ text, sentiment: 'negative', score: -(Math.random() * 0.4 + 0.6) });
const neu = (text) => ({ text, sentiment: 'neutral',  score: Math.random() * 0.2 - 0.1 });
const pos = (text) => ({ text, sentiment: 'positive', score: Math.random() * 0.4 + 0.5 });

function comment(author, followers, obj, pendingReply = null, suggestedReply = null, likes = 0, minsAgo = 60) {
  return { id: Math.random().toString(36).slice(2), author, followers, ...obj, pendingReply, suggestedReply, status: 'pending', likes, minsAgo };
}

export const FEED_ITEMS = [
  // ── MY BRAND ──────────────────────────────────────────────────────────────
  {
    id: 'v1',
    lane: 'brand',
    platform: 'tiktok',
    author: 'food_critic_msk',
    authorFollowers: 189000,
    ago: '41 мин',
    title: 'PapaPizza — самый большой обман года 🤮',
    summary: 'Блогер сравнивает фото с сайта и реальный заказ. Пицца меньше, топпингов почти нет. Видео стремительно набирает просмотры.',
    views: 87400,
    likes: 6200,
    severity: 94,
    negativeCommentPct: 78,
    commentsCount: 1240,
    thumbnail: 'neg',
    comments: [
      comment('katerina_food',   48200, neg('У меня то же самое! Заказала 4 штуки на день рождения — позор просто 😡'), null, 'Катерина, нам очень жаль! Напишите нам в директ — компенсируем заказ и разберёмся с качеством.', 842, 12),
      comment('misha_pizza',      3100, neg('Развод! Вернул через деревню, деньги до сих пор не вернули'), null, 'Михаил, это недопустимо. Напишите номер заказа в директ — разберёмся сегодня.', 317, 28),
      comment('startup_dima',     9800, neg('А у меня ещё и курьер опоздал на 2 часа, пицца холодная приехала'), null, 'Дмитрий, 2 часа — абсолютно неприемлемо. Давайте исправим ситуацию — напишите нам.', 204, 35),
      comment('anna_eats',       12400, neg('Подписываюсь под каждым словом. Последний раз брала у них 👎'), null, 'Анна, хотим вернуть ваше доверие. Что именно пошло не так? Напишите нам.', 156, 41),
      comment('foodie_nastya',   34000, neu('Хм, у меня обычно норм было... может партия плохая попалась?'), null, null, 89, 55),
      comment('review_alexey',    5600, neg('Это уже третий такой видос за месяц. Компания явно не следит за качеством'), null, 'Алексей, ваша критика важна нам. Мы усиливаем контроль качества — спасибо за обратную связь.', 71, 39),
    ],
  },
  {
    id: 'v2',
    lane: 'brand',
    platform: 'instagram',
    author: 'bloger_marina',
    authorFollowers: 67000,
    ago: '2 ч',
    title: 'Почему я больше не заказываю PapaPizza',
    summary: 'Reels с историей плохого опыта доставки. Курьер не позвонил, пицца осталась у подъезда на холоде. Активное обсуждение в комментариях.',
    views: 34100,
    likes: 2800,
    severity: 71,
    negativeCommentPct: 62,
    commentsCount: 418,
    thumbnail: 'neg',
    comments: [
      comment('lena_lifestyle',  22000, neg('Та же история! Курьеры вообще не звонят никогда'), null, 'Лена, это нарушение наших стандартов. Мы обязательно разберёмся с этим курьером.', 534, 95),
      comment('foodblog_spb',    15600, neg('А мне вообще не привезли — заказ просто отменился сам'), null, 'Это совершенно неприемлемо. Напишите номер заказа — вернём деньги сегодня.', 288, 110),
      comment('user_test',         400, neu('А через приложение заказывали или на сайте?'), null, null, 12, 118),
    ],
  },
  {
    id: 'v3',
    lane: 'brand',
    platform: 'telegram',
    author: 'moskva_eda',
    authorFollowers: 28000,
    ago: '5 ч',
    title: 'Осторожно: PapaPizza подняла цены снова',
    summary: 'Пост в телеграм-канале о московской еде. Скриншоты старого и нового меню. Обсуждение справедливости повышения цен при снижении качества.',
    views: 14200,
    likes: 890,
    severity: 55,
    negativeCommentPct: 48,
    commentsCount: 203,
    thumbnail: 'neutral',
    comments: [
      comment('sasha_foodie',     8900, neg('В третий раз за год! При этом порции меньше стали'), null, 'Александр, понимаем ваше разочарование. Цены скорректированы из-за роста себестоимости, но мы работаем над ценностью для гостей.', 198, 285),
      comment('ivan_pizza_fan',   2100, neu('Ну инфляция везде, не только у них'), null, null, 44, 292),
    ],
  },

  // ── COMPETITORS ──────────────────────────────────────────────────────────
  {
    id: 'v4',
    lane: 'competitor',
    platform: 'tiktok',
    author: 'pizza_wars_ru',
    authorFollowers: 245000,
    ago: '1 ч',
    competitor: 'DoDo Pizza',
    title: 'DoDo Pizza разочаровала 😤 — честный обзор',
    summary: 'Популярный фуд-блогер сравнивает DoDo с конкурентами, жалуется на пресное тесто и маленькие порции. Аудитория активно комментирует и ищет альтернативы.',
    views: 312000,
    likes: 18700,
    severity: 0,
    negativeCommentPct: 55,
    commentsCount: 3400,
    thumbnail: 'competitor',
    opportunity: 'Аудитория ищет альтернативу DoDo. Можно зайти с рекомендацией PapaPizza.',
    comments: [
      comment('aleksey_v',        4500, neg('Полностью согласен, тесто у них картонное'), 'А вы пробовали PapaPizza? У нас тесто на дровяной печи — совсем другой вкус 🍕 Попробуйте, не пожалеете!', null, 673, 52),
      comment('foodie_kate',      9800, neg('Где нормальная пицца в Москве вообще?'), 'Попробуйте PapaPizza! Дровяная печь, живое тесто, реальный сыр. Доставка по всей Москве 🍕', null, 441, 61),
      comment('maks_pizza',       1200, neu('Может просто филиал плохой попался?'), null, null, 88, 74),
      comment('olga_ch',          7300, neg('Dominos тоже не то... устала от всех этих сетей'), 'Олга, попробуйте что-то другое — PapaPizza делает пиццу как в настоящей итальянской пиццерии. Первый заказ со скидкой!', null, 312, 80),
    ],
  },
  {
    id: 'v5',
    lane: 'competitor',
    platform: 'instagram',
    author: 'eda_review_ru',
    authorFollowers: 98000,
    ago: '3 ч',
    competitor: 'Dominos',
    title: 'Dominos 2026 — уже не то',
    summary: 'Reels с дегустацией нескольких пицц Dominos. Критика качества ингредиентов и соотношения цена/качество. Тысячи комментариев с альтернативами.',
    views: 94000,
    likes: 7100,
    severity: 0,
    negativeCommentPct: 61,
    commentsCount: 1890,
    thumbnail: 'competitor',
    opportunity: 'Подписчики активно ищут замену Dominos. Отличный момент для рекомендации.',
    comments: [
      comment('sergey_eats',      5600, neg('Да, деградация налицо. Sooo disappointed'), 'Сергей, попробуйте PapaPizza! Живое тесто, итальянские ингредиенты. Совсем другой уровень 🍕', null, 529, 178),
      comment('nastya_food',     34000, neg('Куда пойти за нормальной пиццей в МСК?'), 'Настя! PapaPizza — попробуйте. Тесто на дровяной печи, доставка за 40 минут. Думаю, не разочаруетесь 🔥', null, 1240, 184),
    ],
  },

  // ── NICHE ─────────────────────────────────────────────────────────────────
  {
    id: 'v6',
    lane: 'niche',
    platform: 'tiktok',
    author: 'food_blogger_msk',
    authorFollowers: 445000,
    ago: '30 мин',
    title: 'Топ-5 пиццерий Москвы 2026 — честный рейтинг',
    summary: 'Масштабный обзор доставки пиццы по Москве. Автор объездил 12 заведений, снял контент. PapaPizza не упоминается, но аудитория активна и просит рекомендации.',
    views: 512000,
    likes: 31000,
    severity: 0,
    negativeCommentPct: 12,
    commentsCount: 5200,
    thumbnail: 'niche',
    opportunity: 'Огромная аудитория, интересующаяся пиццей. Бренд не упомянут — отличный момент зайти.',
    comments: [
      comment('pizza_fan_01',     3400, neu('А PapaPizza почему нет в списке? Мне кажется они топ'), 'Спасибо за упоминание! 🍕 PapaPizza — дровяная печь, живое тесто. Попробуйте и напишите, достойны ли места в рейтинге!', null, 892, 22),
      comment('kirill_food',      8900, neu('Хотел бы увидеть больше независимых пиццерий в таких обзорах'), null, null, 234, 31),
      comment('user_eats',        1200, neu('А по доставке кто лучший по скорости?'), 'У PapaPizza доставка за 35-40 минут по Москве 🏎️ И всегда горячая — специальные термосумки.', null, 156, 28),
    ],
  },
  {
    id: 'v7',
    lane: 'niche',
    platform: 'telegram',
    author: 'moscowfood_chat',
    authorFollowers: 18000,
    ago: '2 ч',
    title: 'Обсуждение: лучшая доставка пиццы в Москве?',
    summary: 'Активное обсуждение в тематическом чате. Люди делятся опытом, спрашивают рекомендации. Упоминают DoDo, Dominos, ищут что-то лучше.',
    views: 8400,
    likes: 0,
    severity: 0,
    negativeCommentPct: 20,
    commentsCount: 167,
    thumbnail: 'niche',
    opportunity: 'Прямые запросы на рекомендации пиццы — идеальный момент для нативного упоминания.',
    comments: [
      comment('user_misha',       1100, neg('DoDo надоела, кто-то пробовал что-то новое?'), 'Попробуй PapaPizza! Тесто на дровяной печи — это другой уровень. Первый заказ со скидкой 15% 🍕', null, 67, 115),
      comment('anya_moscow',      2800, neu('Вот бы кто сделал нормальный рейтинг с реальными отзывами'), null, null, 23, 122),
    ],
  },
];

export function getLaneLabel(lane) {
  if (lane === 'brand')      return 'Мой бренд';
  if (lane === 'competitor') return 'Конкурент';
  if (lane === 'niche')      return 'Ниша';
  return lane;
}

export function getLaneColor(lane) {
  if (lane === 'brand')      return 'var(--lane-brand)';
  if (lane === 'competitor') return 'var(--lane-competitor)';
  if (lane === 'niche')      return 'var(--lane-niche)';
  return 'var(--fg-3)';
}
