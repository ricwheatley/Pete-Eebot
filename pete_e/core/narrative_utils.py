import random

# 🔗 Pete’s conversational glue
CONNECTORS = [
    "mate,", "listen,", "honestly,", "you know what?",
    "I swear,", "look,", "trust me,", "real talk,",
    "hear me out,", "no joke,", "straight up,", "let me tell ya,",
    "truth bomb incoming,", "mark my words,", "don’t forget,", "FYI,",
    "between sets,", "spotter says,", "chalk it up,", "on the platform,",
    "in the squat rack,", "cardio corner says,", "coach voice,", "ref’s whistle,",
    "wild thought,", "brace yourself,", "plot twist,", "oh and,",
    "PSA,", "low-key,", "high-key,", "hot take,",
    "story time,", "not gonna lie,", "fun fact,", "spoiler alert,",
    "confession time,", "the crowd goes wild,", "cheeky reminder,", "quick tip,",
    "as legend foretold,", "the prophecy says,", "the gains oracle spoke,",
    "the dumbbell whispered,", "the protein shaker rattled,", "barbell gospel,",
    "in the annals of leg day,", "arm day chronicles,",
    "bro science says,", "peer-reviewed by Pete,", "your muscles requested,",
    "science optional,", "gainz committee reports,", "straight from the creatine cloud,",
]

# 🏁 Pete’s dramatic sign-offs
CLOSERS = [
    "Keep grinding or the gains train leaves without you 🚂💪",
    "Hakuna matata and heavy squatta 🦁🏋️",
    "No excuses, just sets and juices 🥤💪",
    "The dumbbell of destiny calls your name 🔔",
    "Stay swole, stay soulful ✨",
    "Flex now, regret never 💥",
    "DOMS today, swagger tomorrow 😎",
    "Protein shakes > milkshakes 🥛➡️💪",
    "Rack it, stack it, attack it 🏋️",
    "Foam roll with it, baby 🎶",
    "Your quads just paid rent 🏠",
    "Glutes so strong they have their own postcode 📮",
    "You benched reality itself 🛋️",
    "Burpees summoned the apocalypse ☠️",
    "Cardio is still a scam, but you passed 🔥",
    "The mitochondria called — you’re the powerhouse now ⚡",
    "Sweat is just your fat crying tears of defeat 💧",
    "Congrats, you unlocked Beast Mode DLC 🕹️",
    "Leg day skipped? Friendship ended 🛑",
    "Iron sharpens iron, and you’re glowing 🔥",
    "Pain fades, flex remains 💪",
    "The rack remembers who lifts 🏋️",
    "The gym floor salutes your footsteps 👣",
    "Protein never sleeps 🥩",
    "Bench dreams, squat realities 🏋️‍♂️",
    "Victory smells like chalk dust 🧂",
    "DOMS is your love language ❤️",
    "The pump is temporary, glory eternal 🕰️",
    "Pete believes, therefore you achieve 🙌",
    "Your biceps filed a restraining order on sleeves 👕❌",
    "Glutes trending worldwide 🌍",
    "Hamstrings of destiny engaged ⚔️",
    "Triceps tighter than your budget 💸",
    "The spotter in the sky nodded 🙏",
    "Reps today, legends tomorrow 🏆",
    "Lift heavy, love harder ❤️‍🔥",
    "You pressed so hard Newton updated physics 📚",
    "Your sweat just got its own IMDb credit 🎬",
    "Congrats, you broke the space-time flex continuum ⏳💥",
]

# 💥 Chaos one-liners
ONE_LINERS = [
    "DOMS = proof you exist 💥",
    "Burpees? More like slurpees 🥤",
    "Your quads stomp harder than Godzilla in heels 🦖",
    "Proteinpalooza solves everything 🍗",
    "Squatmageddon is coming — brace yourself 🏋️‍♂️",
    "Glutes to the moon 🚀",
    "Hydrate or diedrate 💧",
    "Pain is temporary, flex is forever 💪",
    "No chalk, no glory 🧂➡️🏋️",
    "Bench press your feelings 😤",
    "Legs so fried, KFC took notes 🍗",
    "Abs tighter than your Wi-Fi signal 📶",
    "Your hamstrings signed up for a union ✍️",
    "You just unlocked cardio nightmare mode 👻",
    "Biceps sponsored by NASA 🚀",
    "Sweat equity is real estate 💰",
    "Your core could stop traffic 🚦",
    "Traps visible from space 🛰️",
    "Muscles louder than your playlist 🎧",
    "Your PR is now Pete’s bedtime story 📖",
]


def stitch_sentences(insights: list[str], sprinkles: list[str], short_mode: bool = False) -> str:
    """
    Turn insights + sprinkles into a chatty Pete-style rant.
    If short_mode=True, or by random chance, just return a one-liner.
    """
    if short_mode or random.random() < 0.08:
        return random.choice(ONE_LINERS)

    text = []
    if insights:
        text.append(f"Mate, {insights[0]} — not bad at all.")

    for part in insights[1:]:
        connector = random.choice(CONNECTORS)
        text.append(f"{connector} {part}")

    for s in sprinkles:
        connector = random.choice(CONNECTORS)
        text.append(f"{connector} {s.lower()}")

    text.append(random.choice(CLOSERS))
    return " ".join(text)
