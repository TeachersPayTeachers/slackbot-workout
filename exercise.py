import random
import requests
import json
import csv
import os
from random import shuffle
import pickle
import os.path
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from User import User

load_dotenv('.env')

# Environment variables must be set with your tokens
USER_TOKEN_STRING =  os.environ['SLACK_USER_TOKEN_STRING']
URL_TOKEN_STRING =  os.environ['SLACK_URL_TOKEN_STRING']

HASH = "%23"


# Configuration values to be set in setConfiguration
class Bot:
    def __init__(self):
        self.setConfiguration()

        self.csv_filename = "log" + time.strftime("%Y%m%d-%H%M") + ".csv"
        self.first_run = True

        # local cache of usernames
        # maps userIds to usernames
        self.user_cache = self.loadUserCache()

        # round robin store
        self.user_queue = []

    def loadUserCache(self):
        if os.path.isfile('user_cache.save'):
            with open('user_cache.save','rb') as f:
                self.user_cache = pickle.load(f)
                print "Loading " + str(len(self.user_cache)) + " users from cache."
                return self.user_cache

        return {}

    def setConfiguration(self):
        """
        Sets the configuration file.

        Runs after every callout so that settings can be changed realtime
        """
        # Read variables fromt the configuration file
        with open('config.json') as f:
            settings = json.load(f)

            self.team_domain = os.environ['TEAM_DOMAIN']
            self.channel_name = os.environ['CHANNEL_NAME']
            self.min_countdown = settings["callouts"]["timeBetween"]["minTime"]
            self.max_countdown = settings["callouts"]["timeBetween"]["maxTime"]
            self.num_people_per_callout = settings["callouts"]["numPeople"]
            self.sliding_window_size = settings["callouts"]["slidingWindowSize"]
            self.group_callout_chance = settings["callouts"]["groupCalloutChance"]
            self.channel_id = os.environ['CHANNEL_ID']
            self.exercises = settings["exercises"]
            self.start_hour = settings["workoutTime"]["startHour"]
            self.end_hour = settings["workoutTime"]["endHour"]

            self.debug = settings["debug"]

        self.post_URL = "https://" + self.team_domain + ".slack.com/services/hooks/slackbot?token=" + URL_TOKEN_STRING + "&channel=" + HASH + self.channel_name


################################################################################
'''
Selects an active user from a list of users
'''
def selectUser(bot, exercise):
    active_users = fetchActiveUsers(bot)

    # Add all active users not already in the user queue
    # Shuffles to randomly add new active users
    shuffle(active_users)
    bothArrays = set(active_users).intersection(bot.user_queue)
    for user in active_users:
        if user not in bothArrays:
            bot.user_queue.append(user)

    # The max number of users we are willing to look forward
    # to try and find a good match
    sliding_window = bot.sliding_window_size

    # find a user to draw, priority going to first in
    for i in range(len(bot.user_queue)):
        user = bot.user_queue[i]

        # User should be active and not have done exercise yet
        if user in active_users and not user.hasDoneExercise(exercise):
            bot.user_queue.remove(user)
            return user
        elif user in active_users:
            # Decrease sliding window by one. Basically, we don't want to jump
            # too far ahead in our queue
            sliding_window -= 1
            if sliding_window <= 0:
                break

    # If everybody has done exercises or we didn't find a person within our sliding window,
    for user in bot.user_queue:
        if user in active_users:
            bot.user_queue.remove(user)
            return user

    # If we weren't able to select one, just pick a random
    print "Selecting user at random (queue length was " + str(len(bot.user_queue)) + ")"
    return active_users[random.randrange(0, len(active_users))]


'''
Fetches a list of all active users in the channel
'''
def fetchActiveUsers(bot):
    # Check for new members
    params = {"token": USER_TOKEN_STRING, "channel": bot.channel_id}
    response = requests.get("https://slack.com/api/channels.info", params=params)
    user_ids = json.loads(response.text, encoding='utf-8')["channel"]["members"]

    active_users = []

    for user_id in user_ids:
        # Add user to the cache if not already
        if user_id not in bot.user_cache:
            bot.user_cache[user_id] = User(user_id)
            if not bot.first_run:
                # Push our new users near the front of the queue!
                bot.user_queue.insert(2,bot.user_cache[user_id])

        if bot.user_cache[user_id].isActive():
            active_users.append(bot.user_cache[user_id])

    if bot.first_run:
        bot.first_run = False

    return active_users


def announce_next_lottery_time(bot, exercise, next_time_interval):
    """
    Make an announcement about the next exercise lottery

    :param bot:
    :param exercise:
    :param next_time_interval:
    :return:
    """
    # Announcement String of next lottery time
    lottery_announcement = "Next Lottery for {} is in {} minutes.".format(
        exercise["name"].upper(),
        str(next_time_interval/60))

    # Announce the exercise to the thread
    if not bot.debug:
        requests.post(bot.post_URL, data=lottery_announcement)
    print(lottery_announcement)


def select_exercise(bot):
    """
    Select the next exercise

    :param bot:
    :return:
    """
    return bot.exercises[random.randrange(0, len(bot.exercises))]


def select_next_time_interval(bot):
    """
    Get a random time within the bot's range

    :param bot:
    :return:
    """
    return random.randrange(bot.min_countdown * 60, bot.max_countdown * 60)


def assign_exercise(bot, exercise):
    """
    Selects a person to do the already-selected exercise

    :param bot:
    :param exercise:
    :return:
    """
    # Select number of reps
    exercise_reps = random.randrange(exercise["minReps"], exercise["maxReps"]+1)

    winner_announcement = str(exercise_reps) + " " + str(exercise["units"]) + " " + exercise["name"] + " Right Now! "

    # EVERYBODY
    if random.random() < bot.group_callout_chance:
        winner_announcement += "@here!"

        for user_id in bot.user_cache:
            user = bot.user_cache[user_id]
            user.addExercise(exercise, exercise_reps)

        logExercise(bot, "@here", exercise["name"], exercise_reps, exercise["units"])

    else:
        winners = [selectUser(bot, exercise) for _ in range(bot.num_people_per_callout)]

        for i in range(bot.num_people_per_callout):
            winner_announcement += str(winners[i].getUserHandle())
            if i == bot.num_people_per_callout - 2:
                winner_announcement += ", and "
            elif i == bot.num_people_per_callout - 1:
                winner_announcement += "!"
            else:
                winner_announcement += ", "

            winners[i].addExercise(exercise, exercise_reps)
            logExercise(bot, winners[i].getUserHandle(), exercise["name"], exercise_reps, exercise["units"])

    # Announce the user
    if not bot.debug:
        requests.post(bot.post_URL, data=winner_announcement)
    print (winner_announcement)


def logExercise(bot,username,exercise,reps,units):
    filename = bot.csv_filename + "_DEBUG" if bot.debug else bot.csv_filename
    with open(filename, 'a') as f:
        writer = csv.writer(f)

        writer.writerow([str(datetime.now()),username,exercise,reps,units,bot.debug])

def saveUsers(bot):
    # Write to the command console today's breakdown
    s = "```\n"
    #s += "Username\tAssigned\tComplete\tPercent
    s += "Username".ljust(15)
    for exercise in bot.exercises:
        s += exercise["name"] + "  "
    s += "\n---------------------------------------------------------------\n"

    for user_id in bot.user_cache:
        user = bot.user_cache[user_id]
        s += user.username.ljust(15)
        for exercise in bot.exercises:
            if exercise["id"] in user.exercises:
                s += str(user.exercises[exercise["id"]]).ljust(len(exercise["name"]) + 2)
            else:
                s += str(0).ljust(len(exercise["name"]) + 2)
        s += "\n"

        user.storeSession(str(datetime.now()))

    s += "```"

    if not bot.debug:
        requests.post(bot.post_URL, data=s)
    print s


    # write to file
    with open('user_cache.save','wb') as f:
        pickle.dump(bot.user_cache,f)


def workout_time(bot):
    return (bot.start_hour <= (datetime.now() - timedelta(hours=4)).hour < bot.end_hour and
            # If the day of week is Monday - Friday
            0 <= datetime.now().today().weekday() <= 4)


def save_user_time():
    """
    Creates a DateTime object with correct save time

    Checks if that save time is now
    """
    save_time = datetime.utcnow().replace(hour=18, minute=0, second=0, microsecond=0)
    return (save_time == (datetime.utcnow() - timedelta(hours=4)))


def is_valid_interval(bot, sleep_interval):
    """
    Check if the given sleep_interval is still within the bot's
    valid time range

    :param bot:
    :param sleep_interval:
    :return:
    """
    now = datetime.now() - timedelta(hours=4)
    next_interval_hour = (now + timedelta(minutes=(sleep_interval/60))).hour

    return bot.start_hour <= next_interval_hour < bot.end_hour


def main():
    bot = Bot()

    while True:
        if workout_time(bot):
            # Re-fetch config file if settings have changed
            bot.setConfiguration()

            # Get the next sleep interval; in seconds for use with `time.sleep()`
            sleep_interval = select_next_time_interval(bot)

            # If the next interval is within valid hours
            if is_valid_interval(bot, sleep_interval):
                # Get an exercise to do
                exercise = select_exercise(bot)

                # Announce the next lottery
                announce_next_lottery_time(bot, exercise, sleep_interval)

                # Sleep
                time.sleep(sleep_interval)

                # Assign the exercise to someone
                assign_exercise(bot, exercise)

        if save_user_time():
            saveUsers(bot)


if '__main__' == __name__:
    main()
