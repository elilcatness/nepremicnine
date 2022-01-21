import os

import requests
from dotenv import load_dotenv
from lxml import html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.error import BadRequest
from telegram.ext import Updater, CommandHandler, CallbackContext

from src import db_session
from src.mail import Mail

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/91.0.4472.124 Safari/537.36'}


def get_doc(url: str, **kwargs):
    response = requests.get(url, **kwargs)
    if not response:
        return None
    return html.fromstring(response.text)


def _load_ads_from_db() -> list[str]:
    with db_session.create_session() as session:
        mail = session.query(Mail).first()
        if not mail or not mail.ads:
            return []
        return mail.ads.split(';')


def safe_get(array, index, default=None):
    try:
        return array[index]
    except IndexError:
        return default


def parse_page(url: str, **kwargs):
    doc = get_doc(url, **kwargs)
    if not doc:
        return print(f'Failed to parse {url}')
    title = safe_get(doc.xpath('//h1[@class="podrobnosti-naslov"]'), 0)
    if title is not None:
        title = title.text_content().strip()
    description = safe_get(doc.xpath('//meta[@itemprop="description"]/@content'), 0)
    price = safe_get(doc.xpath('//div[@class="cena clearfix"]'), 0)
    if price is not None:
        price = price.text_content().strip()
    img = safe_get(doc.xpath('//a[@class="rsImg"]'), 0)
    if img:
        img = img.get('href')
    return {'url': url, 'Title': title, 'Description': description, 'Price': price, 'img': img}


def get_last_ads(url: str, count: int = 5) -> tuple:
    domain = '//'.join(url.split('/')[:3:2])
    doc = get_doc(url, headers=HEADERS)
    error_msg = f'Failed to get last_ads in {url}'
    if not doc:
        return print(error_msg), None
    ads = doc.xpath('//a[@class="slika"]')
    if not ads:
        return print(error_msg), None
    last_req_ads = _load_ads_from_db()
    last_ads = []
    new_ads = []
    for ad in ads[:count] if count < len(ads) else ads:
        url = domain + ad.get('href')
        if url not in last_req_ads:
            url_data = parse_page(url, headers=HEADERS)
            if not url_data:
                return None, None
            new_ads.append(url_data)
        else:
            last_ads.append(ad)
    return new_ads, last_ads


def process(context: CallbackContext):
    user_id = context.job.context.user_data['id']
    with db_session.create_session() as session:
        mail = session.query(Mail).get(user_id)
        new_ads, last_ads = get_last_ads(os.getenv('url'))
        if not new_ads:
            return
        if last_ads:
            last_ads = last_ads[::-1]
        for i, ad in enumerate(new_ads):
            print(ad)
            url, photo = ad.pop('url'), ad.pop('img')
            text = ('New notification!\n\n' + '\n'.join(
                [f'<b>{key}</b>: {val}' for key, val in ad.items()]))
            markup = InlineKeyboardMarkup([[InlineKeyboardButton('Open ad', url=url)]])
            kwargs = {'reply_markup': markup, 'parse_mode': ParseMode.HTML}
            photo_sent = False
            if photo:
                try:
                    context.bot.send_photo(user_id, photo, text, **kwargs)
                    photo_sent = True
                except BadRequest:
                    pass
            if not photo_sent:
                context.bot.send_message(user_id, text, **kwargs)
            if i < len(last_ads):
                last_ads[i] = url
            else:
                last_ads.append(url)
        mail.ads = ';'.join(last_ads[::-1])
        session.add(mail)
        session.commit()


def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    with db_session.create_session() as session:
        mail = session.query(Mail).get(user_id)
        if mail:
            return update.message.reply_text('Notifications have already been activated')
        mail = Mail(user_id=user_id)
        session.add(mail)
        session.commit()
    context.user_data['id'] = user_id
    context.job_queue.run_repeating(process, 10, context=context, name=str(user_id))
    return update.message.reply_text('Notifications have been activated')


def start_last_mails(dispatcher, bot):
    session = db_session.create_session()
    for mail in session.query(Mail).all():
        context = CallbackContext(dispatcher)
        context._bot = bot
        context._user_data = {'id': mail.user_id}
        context.job_queue.run_repeating(process, 10, context=context, name=str(mail.user_id))


def main():
    updater = Updater(os.getenv('token'))
    updater.dispatcher.add_handler(CommandHandler('start', start))
    start_last_mails(updater.dispatcher, updater.bot)
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    load_dotenv()
    db_session.global_init(os.getenv('DATABASE_URL'))
    main()
