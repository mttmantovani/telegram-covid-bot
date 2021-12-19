import codecs
import io
import logging
import os
import re
from datetime import date
from datetime import datetime as dt
from datetime import time
from datetime import timedelta as td

import boto3
import botocore
import geopandas as gpd
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import pytz
import requests
from jinja2 import Template
from telegram import InputMediaPhoto, Update
from telegram.ext import CallbackContext, CommandHandler, Updater

from fetch import regions, get_vaccines_data, load_df, get_population

if os.environ.get("WITH_AWS", None):
    session = boto3.Session(
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", None),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", None),
    )
    s3 = session.resource("s3")


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)

if "TELEGRAM_TOKEN" in os.environ:
    token = os.environ.get("TELEGRAM_TOKEN", None)
else:
    with open("token.txt", "r") as tk:
        token = tk.readline().strip()

PORT = int(os.environ.get("PORT", "8443"))


data_src = "https://raw.githubusercontent.com/italia/covid19-opendata-vaccini/master/dati/somministrazioni-vaccini-summary-latest.csv"
pop_src = "https://www.worldometers.info/world-population/italy-population/"
pop_exp = r"The current population of <strong>Italy</strong> is <strong>(.*?)</strong>"
pop_pattern = re.compile(pop_exp)


def send_to_S3(filename):
    # Filename - File to upload
    # Bucket - Bucket to upload to (the top level directory under AWS S3)
    # Key - S3 object name (can contain subdirectories). If not specified then file_name is used
    s3.meta.client.upload_file(
        Filename=filename,
        Bucket=os.environ.get("S3_BUCKET_NAME", None),
        Key=filename,
    )


def get_from_S3(filename):
    try:
        s3.Bucket(os.environ.get("S3_BUCKET_NAME", None)).download_file(
            filename, filename
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            print("The object does not exist.")
        else:
            raise


def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        "Hi! I'm VaccineItalyBot. You can get the latest data \
about COVID vaccinations in Italy with the command <b>/latest</b>. \
Subscribe to get daily updates: \
<b>/subscribe</b>. Or <b>/unsubscribe</b>.\n \
<b>/plot</b> to see a chart of vaccinations for Italy, \
or <b>/plot regione</b> for info region by region. Example: /plot Liguria",
        parse_mode="HTML",
    )


def help_command(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    update.message.reply_text("Here will go help message")


def latest(update: Update, context: CallbackContext) -> None:
    data = get_vaccines_data()
    data["date"] = dt.now().strftime("%b %-d, %Y - %H:%M")
    with codecs.open("template.html", "r", encoding="UTF-8") as file:
        template = Template(file.read())
        update.message.reply_text(template.render(**data), parse_mode="HTML")


def latest_job(context):
    today = dt.now().strftime("%Y-%m-%d")
    ts = dt.now().strftime("%Y%m%d-%H%M")

    data = get_vaccines_data()
    data["date"] = dt.now().strftime("%b %-d, %Y - %H:%M")
    with codecs.open("template.html", "r", encoding="UTF-8") as file:
        template = Template(file.read())

    job = context.job

    today_wordy = dt.now().strftime("%b %-d, %Y")

    plot_urls = [
        f"https://mttmantovani.s3.eu-central-1.amazonaws.com/charts/latest-{plot}.png?a={ts}"
        for plot in ["total", "daily", "map"]
    ]
    captions = [f"Daily report of {today_wordy}", "", ""]

    plots = [InputMediaPhoto(url, caption) for url, caption in zip(plot_urls, captions)]

    context.bot.send_message(
        job.context, text=template.render(**data), parse_mode="HTML"
    )
    context.bot.send_media_group(job.context, plots)


def plot(update: Update, context: CallbackContext) -> None:
    today = dt.now().strftime("%Y-%m-%d")
    today_wordy = dt.now().strftime("%b %-d, %Y")
    ts = dt.now().strftime("%Y%m%d-%H%M")

    if context.args:
        found = False
        for abbr, name in regions.items():
            for arg in context.args:
                if arg.lower() in (_n.lower() for _n in name):
                    region_name = name[0]
                    region_abbr = abbr
                    found = True
        if not found:
            update.message.reply_text("Regione inesistente.")
            return
    else:
        region_name = "Italy"
        region_abbr = "ITA"

    if region_name == "Italy":
        plot_urls = [
            f"https://mttmantovani.s3.eu-central-1.amazonaws.com/charts/latest-{plot}.png?a={ts}"
            for plot in ["total", "daily", "map"]
        ]
        captions = [f"Summary plots of {today_wordy}", "", ""]
    else:
        plot_urls = [
            f"https://mttmantovani.s3.eu-central-1.amazonaws.com/charts/regions/{region_abbr.lower()}-{plot}.png?a={ts}"
            for plot in ["total", "daily"]
        ]
        captions = [f"Summary plots of {today_wordy} for {region_name}", ""]

    plots = [InputMediaPhoto(url, caption) for url, caption in zip(plot_urls, captions)]

    update.message.reply_media_group(plots)


def is_subscribed(name, context):
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    return True


def remove_subscription(name, context):
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()

    with open("subscribed_users.txt", "r") as su:
        users = su.readlines()

    with open("subscribed_users.txt", "w") as su:
        for user in users:
            if user.strip("\n") != name:
                su.write(user)
    if os.environ.get("WITH_AWS", None):
        send_to_S3("subscribed_users.txt")


def subscribe(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id

    if is_subscribed(str(chat_id), context):
        text = "You are already subscribed."
    else:
        context.job_queue.run_daily(
            latest_job,
            time(hour=20, tzinfo=pytz.timezone("Europe/Rome")),
            days=(0, 1, 2, 3, 4, 5, 6),
            context=chat_id,
            name=str(chat_id),
        )

        with open("subscribed_users.txt", "a") as su:
            su.write(str(chat_id) + "\n")
        if os.environ.get("WITH_AWS", None):
            send_to_S3("subscribed_users.txt")
        text = "You will receive daily updates at 20:00 CET."

    update.message.reply_text(text)


def unsubscribe(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id

    if is_subscribed(str(chat_id), context):
        remove_subscription(str(chat_id), context)
        text = "You will no longer receive the latest updates."
    else:
        text = (
            "You are not currently subscribed. Use /subscribe to receive daily updates."
        )
    update.message.reply_text(text)


def goodbot(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    update.message.reply_text("Grazie, mio padrone.")


def badbot(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    update.message.reply_text("\U0001f62d")


def main():
    updater = Updater(token, use_context=True)

    if os.environ.get("WITH_AWS", None):
        get_from_S3("subscribed_users.txt")
    if os.path.isfile("subscribed_users.txt"):
        with open("subscribed_users.txt", "r") as su:
            subscribed_users = [s.strip("\n") for s in su.readlines()]
    else:
        subscribed_users = []
        times = []

    for user in subscribed_users:
        updater.job_queue.run_daily(
            latest_job,
            time(hour=20, tzinfo=pytz.timezone("Europe/Rome")),
            days=(0, 1, 2, 3, 4, 5, 6),
            context=user,
            name=user,
        )

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("latest", latest))
    dispatcher.add_handler(CommandHandler("plot", plot))
    dispatcher.add_handler(CommandHandler("subscribe", subscribe))
    dispatcher.add_handler(CommandHandler("unsubscribe", unsubscribe))
    dispatcher.add_handler(CommandHandler("goodbot", goodbot))
    dispatcher.add_handler(CommandHandler("badbot", badbot))

    if os.environ.get("IS_HEROKU", None):
        updater.start_webhook(listen="0.0.0.0", port=PORT, url_path=token)
        # updater.bot.set_webhook(url=settings.WEBHOOK_URL)
        updater.bot.set_webhook(
            "https://{}.herokuapp.com/".format(os.environ.get("APP_NAME", None)) + token
        )
    else:
        updater.start_polling()

    updater.idle()


if __name__ == "__main__":
    main()
