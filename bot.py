import io
import requests
import re
import pandas as pd
import logging
import os
from datetime import datetime as dt
from datetime import timedelta as td
from datetime import date, time, timezone
import pytz

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from jinja2 import Template
import codecs
import pickle

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)


with open('token.txt', 'r') as tk:
    token = tk.readline().strip()

data_src = 'https://raw.githubusercontent.com/italia/covid19-opendata-vaccini/master/dati/somministrazioni-vaccini-summary-latest.csv'
pop_src = 'https://www.worldometers.info/world-population/italy-population/' 
pop_exp = r'The current population of <strong>Italy</strong> is <strong>(.*?)</strong>'
pop_pattern = re.compile(pop_exp)

def get_population():
    r = requests.get(pop_src)
    it_pop = int(re.search(pop_pattern, r.text)[1].replace(',', ''))
    return it_pop

def load_df():
    r = requests.get(data_src)
    df = pd.read_csv(io.StringIO(r.text), index_col='data_somministrazione')
    df.index = pd.to_datetime(df.index, format="%Y-%m-%d")
    df = df.loc[df.area == 'ITA']

    return df

def get_vaccines_data():

    df = load_df()

    population = get_population()
    total_doses = df.totale.sum()
    total_first_dose = df.prima_dose.sum()
    total_second_dose = df.seconda_dose.sum()

    last_week_data = df.loc[df.index > df.index[-1] - td(days=7)]
    lw_total_doses = last_week_data.totale.sum()
    avg_lw_doses = lw_total_doses/7
    avg_lw_first_dose = last_week_data.prima_dose.sum()/7
    avg_lw_second_dose = last_week_data.seconda_dose.sum()/7

    previous_week_data = df.loc[(df.index > df.index[-8] - td(days=7)) & (df.index <= df.index[-1] - td(days=7))]
    pw_total_doses = previous_week_data.totale.sum()
    avg_pw_doses = pw_total_doses/7
    avg_pw_first_dose = previous_week_data.prima_dose.sum()/7
    avg_pw_second_dose = previous_week_data.seconda_dose.sum()/7

    days_to_herd = (0.7*population - total_doses * 0.5) / (avg_lw_doses * 0.5)
    herd_date = df.index[-1] + td(days=days_to_herd)
    
    today = date(dt.now().year, dt.now().month, dt.now().day)
    yesterday = today - td(days=1)
    last_day_data = df.loc[df.index == pd.to_datetime(yesterday, format="%Y-%m-%d") ]
    previous_day_data = df.loc[df.index == pd.to_datetime(yesterday - td(days=1), format="%Y-%m-%d")]
    

    vaccines_data = {
        'total_doses': total_doses,
        'total_first_dose': total_first_dose,
        'total_second_dose': total_second_dose,
        'pc_first_dose': total_first_dose / population * 100,
        'pc_second_dose': total_second_dose / population * 100,
        'lw_total_doses': lw_total_doses,
        'avg_lw_doses': avg_lw_doses,
        'pc_lw_doses': avg_lw_doses / population * 100,
        'avg_lw_first_dose': avg_lw_first_dose,
        'avg_lw_second_dose': avg_lw_second_dose,
        'y_total_doses': last_day_data.totale.sum(),
        'y_first_doses': last_day_data.prima_dose.sum(),
        'y_second_doses': last_day_data.seconda_dose.sum(),
        'pd_total_doses': previous_day_data.totale.sum(),
        'pd_first_doses': previous_day_data.prima_dose.sum(),
        'pd_second_doses': previous_day_data.seconda_dose.sum(),
        'pc_y_doses': (last_day_data.totale.sum() - previous_day_data.totale.sum())/(previous_day_data.totale.sum()) * 100,
        'pc_pw_doses': 100 * (lw_total_doses - pw_total_doses)/pw_total_doses,
        'days_to_herd': days_to_herd,
        'herd_date': herd_date,
    }

    return vaccines_data

def plot_daily_doses():

    df = load_df()

    fig, ax = plt.subplots()
    today = dt.now().strftime("%Y-%m-%d")

    ax.set_title(dt.now().strftime('%b %-d, %Y'))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.set_ylabel('Daily doses')
    
    ax.bar(df.index, df.prima_dose, label='1st dose')
    ax.bar(df.index, df.seconda_dose, bottom=df.prima_dose, label='2nd dose')
    
    fig.autofmt_xdate()
    
    ax.legend(frameon=False)
    
    plt.savefig('charts/'+today+'-daily.png', dpi=300)
    
def plot_cumulative():

    df = load_df()

    fig, ax = plt.subplots()
    today = dt.now().strftime("%Y-%m-%d")
    ax.set_title('Total doses as of ' + dt.now().strftime('%b %-d, %Y'))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.set_ylabel('Total doses')
    

    ax.plot(df.prima_dose.cumsum(), marker='o', label='1st dose')
    ax.plot(df.seconda_dose.cumsum(), marker='o', label='2nd dose')
    ax.plot(df.totale.cumsum(), marker='o', color='ForestGreen', label='Total')
    ax.legend(frameon=False, loc='best')
    fig.autofmt_xdate()
    plt.savefig('charts/'+today+'-total.png', dpi=300)

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Hi! I'm VaccineItalyBot. You can get the latest data \
about COVID vaccinations in Italy with the command <b>/latest</b>. \
Subscribe to get daily updates: \
<b>/subscribe</b>. Or <b>/unsubscribe</b>.\n \
<b>/plot</b> to see a chart of vaccinations.", parse_mode='HTML')

def help_command(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    update.message.reply_text('Here will go help message')

def latest(update: Update, context: CallbackContext) -> None:
    data = get_vaccines_data()
    data['date'] = dt.now().strftime('%b %-d, %Y - %H:%M')
    with codecs.open('template.html', 'r', encoding='UTF-8') as file:
        template = Template(file.read())
        update.message.reply_text(template.render(**data), parse_mode='HTML')

def latest_job(context):
    data = get_vaccines_data()
    data['date'] = dt.now().strftime('%b %-d, %Y - %H:%M')
    with codecs.open('template.html', 'r', encoding='UTF-8') as file:
        template = Template(file.read())

    job = context.job
    context.bot.send_message(job.context, text=template.render(**data), 
            parse_mode='HTML')

def plot(update: Update, context: CallbackContext) -> None:
    today = dt.now().strftime("%Y-%m-%d")
    plot_daily_doses()
    plot_cumulative()
    update.message.reply_photo(open('charts/'+today+'-total.png', 'rb'))
    update.message.reply_photo(open('charts/'+today+'-daily.png', 'rb'))

def is_subscribed(name, context):
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    return True

def remove_subscription(name, context):
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()

def subscribe(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id

    if is_subscribed(str(chat_id), context):
        text = 'You are already subscribed.'
    else:    
        context.job_queue.run_daily(latest_job, time(hour=13, minute=40, tzinfo=pytz.timezone('Europe/Rome')), days=(0,1,2,3,4,5,6), context=chat_id, name=str(chat_id))
        text = 'You will receive daily updates at 13:40 CET.'
    update.message.reply_text(text)

def unsubscribe(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id

    if is_subscribed(str(chat_id), context):
        remove_subscription(str(chat_id), context)
        text = "You will no longer receive the latest updates."
    else:
        text = "You are not currently subscribed. Use /subscribe to receive daily updates."
    update.message.reply_text(text)


def main():
    updater = Updater(token, use_context=True)

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('help', help_command))
    dispatcher.add_handler(CommandHandler('latest', latest))
    dispatcher.add_handler(CommandHandler('plot', plot))
    dispatcher.add_handler(CommandHandler('subscribe', subscribe))
    dispatcher.add_handler(CommandHandler('unsubscribe', unsubscribe))
  
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()



