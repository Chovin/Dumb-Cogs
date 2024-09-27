<!-- omit in toc -->
# Contributing to Dumb-Cogs

First of all, thank you for taking the time to contribute! ❤️

All types of contributions are encouraged and valued. See the [Table of Contents](#table-of-contents) for different ways to help and details on how. Please make sure to read the relevant section before making your contribution. It will make it a lot easier me to go through the contributions and will smooth out the experience for all involved. I look forward to you contributions! 🎉

<!-- omit in toc -->
## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [I Have a Question](#i-have-a-question)
- [I Want To Contribute](#i-want-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
    - [Your first code contribution](#your-first-code-contribution)
    - [I Want to Add More Monsters to the Invasion Cog](#i-want-to-add-more-monsters-to-the-invasion-cog)

## Code of Conduct

Everyone involved with this repo agrees to be respectful and to follow the golden rule. Disputes will be handled calmly and professionally. All interactions with this repo should leave people smiling at the end of the day. 😊

## I Have a Question

If you have any questions about this repo, how to contribute, or how to use the cogs, feel free to message me (Chovin) on discord. You can find me in [Red's Discord server](https://discord.gg/red).

## I Want To Contribute

### Reporting Bugs

<!-- omit in toc -->
#### Before Submitting a Bug Report

A good bug report shouldn’t leave others needing to chase you up for more information. Therefore, I ask you to investigate carefully, collect information and describe the issue in detail in your report. Please complete the following steps in advance to help us fix any potential bug as fast as possible:

* Make sure that you are using the latest version.
* Determine if your bug is really a bug and not an error on your side
* Make sure you check the `[p]help` for the relavent cogs/commands to see if you're missing something that's already addressed
* To see if other users have experienced (and potentially already solved) the same issue you are having, check if there is not already a bug report existing for your bug or error in the [bug tracker](https://github.com/Chovin/Dumb-Cogs/issues?q=label%3Abug).
* Collect information about the bug:
  * Full error (if any) from Red's console
  * OS, Platform and Version (Linux, Mac, Windows, x86, ARM)
  * Possibly your input and output
  * Can you reliably reproduce the issue? What are the steps to reproduce it?

<!-- omit in toc -->
#### How Do I Submit a Good Bug Report?

We use GitHub issues to track bugs and errors. If you run into an issue with any cogs:

- Open an [Issue](https://github.com/Chovin/Dumb-Cogs//issues/new).
- Explain the behavior you would expect and the actual behavior.
- Please provide as much context as possible and describe the *reproduction steps* that someone else can follow to recreate the issue on their own. This usually includes any command arguments (or code for the Pico8 cog for example) and relevant screenshots.  For good bug reports you should isolate the problem and create a reduced test case.
- Provide the information you collected in the previous section.

Once it's submitted:

- I will label the issue accordingly
- When time permits, I will try to reproduce the issue with your provided steps. If no steps were provided, I will add the `needs-repro` label and those with that label will not be addressed until they are reproduced.
- If I am able to reproduce the issue, it will be marked as `needs-fix` as well as possibly other tags (such as `critical`), and the issue will be left to be [implemented by someone](#your-first-code-contribution).

### Suggesting Enhancements

#### Your first code contribution

Congrats! You've decided to make a contribution. That's a great first start! I'll explain in this section how you can go about requesting for that change to be made a part of the project. If you have any questions at all after reading through this section, feel free to reach out to me on Discord (Chovin). 

* The first thing you should do is check to see if what you want to work on is already being made by someone by checking out the [issue list](https://github.com/Chovin/Dumb-Cogs/issues). If it is there, you could leave a comment saying you'd like to help then start a conversation about how you could.
* If it isn't in the issue list already, go ahead and [make a new issue](https://github.com/Chovin/Dumb-Cogs/issues/new) and in detail describe what you it is you want to add/change. Keep note of the issue number of your created issue.
* Once you've done that, [fork the project](https://github.com/Chovin/Dumb-Cogs/fork).
* You can make your changes directly on GitHub. If you need to add files/folders, you can upload them by dragging and dropping them into GitHub, just make sure you put them in the correct folder. Once you've added your changes, select `Create a new branch` and name it with a descriptive name (prefix it with `feature/` or `fix/` accordingly), then click `Propose changes`.
  - <img width="430" alt="image" src="https://github.com/user-attachments/assets/e12e7a65-217c-4534-b418-e125644607e8">
* When making a pull request (PR), make sure you're comparing it with `Chovin/Dumb-Cogs` (click `compare across forks` if you don't see a way to change it to `Chovin/Dumb-Cogs`). Make sure you add a descriptive title, a detailed description (including screenshots helps) with a reference to the issue number like `#2` and then click `Create pull request`.
  - <img width="639" alt="pr" src="https://github.com/user-attachments/assets/861c30e9-7735-4e87-9950-23de26a99416">
* If you need to add files or changes to your PR, make sure you go back to your fork and switch to the branch that the PR is on before adding your files.
  - ![new files](https://github.com/user-attachments/assets/c78845db-9a3a-4d0c-8c5a-4bc824a1c9a7)

#### I Want to Add More Monsters to the Invasion Cog

Monster data is bundled with the cog and is located in [invasion/data/enemies/](invasion/data/enemies). Each monster has its own folder which contains a `stats.json` file and an `animations` folder.

After [forking the repo](#your-first-code-contribution), to make a new monster, you simply need to make a folder for that monster in [invasion/data/enemies/](invasion/data/enemies) with a `stats.json` file and an `animations` folder.

The `stats.json` file controls everything about the monster. Let's look at an excerpt/altered version of the jelly monster's `stats.json` as an example.

> * notice, the formatting of this file is important. `{}`, `[]`, `,`, `"`, and `:` are important characters and should be used where appropriate
> * The `//` characters and what follows them are just placed here to explain the example. They shouldn't be used in your final `stats.json`
> * `...` just represents parts of the `stats.json` that got left out. These shouldn't appear in your `stats.json` either.

`jelly/stats.json`:
```json
{
    "name": "Jelly Alien", // the name of the monster. This will be used in messages

    "lingers": 5, // number of minutes that the monster stays before leaving

    "health": 12, // the health of the monster

    "armor": 0, // the base armor of the monster. This should be between 0 and 1
        // (0 for no armor and 1 for completely blocks all damage)

    "reward_mult": 1, // the multiplier to apply to the reward given to the players if they defeat the monster

    "enrage_titles_override": null, // a list of titles that an enraged monster has
        // in order from least enraged to most enraged. Should be null if you want to
        // use the default list, otherwise, the list should look like
        // for example ["Angered", "Psycho""," "Legendary", "God"]

    "arrival_weight": 1, // the chance that this monster will spawn,
        // For example, 1 is normal, 2 is twice as likely to spawn, 0.5 is half as likely

    "states": { // the states that the monster can be in.
        // These correlate to the different animations you'll see the monster has.
        // Each monster must have the "arriving", "dying", and "attacking" states

        "arriving": { // The state that the monster will first appear in

            "msg": ["Get ready to defend your server!", "Example second message"], // a list of messages to choose
                // from to display when the monster enters this state.
                // Note that the messages are double quoted and comma separated. This field is required
                // this field can be left as an empty list: []
                // in which case nothing will be shown in the description

            "sprite": "arriving.gif", // optional name of the file that should be displayed
                // when the monster enters this state. If sprite is not included then
                // the bot will look for any file in the animations directory that is named
                // after the state, for example, the sprite field isn't required for this
                // state since arriving.gif would already be selected by the bot since
                // the file name (excluding the extension) is "arriving"

            "countdown": 60 // the amount of seconds that the bot is in this state.
                // If a list with 2 values is given, a random time between the first value
                // and the second value is chosen each time the monster enters this state.
                // For example, [10, 30] would make the enemy wait between 10 and 30 seconds.
                // 5 seconds is the minimum for this value

        },
        "dying": {
            "msg": [ 
                "You scare off the {name}...",
                "You blow up the {name} and its ship! ..." // note that you can use {name} in
                    // the message to have the bot replace it with the monster's name.
                    // You should use this instead of manually writing out the name
                    // since the bot will display the enraged title as well.
            ],

            "title_msg": [ // an optional field. A list of title messages to be
                // randomly shown once the monster enters this state.
                "{name} melts into a liquidy blob."
            ]
        },
        "attacking": {
            "msg": [
                ...
            ],
            "damage": 1 // an optional field. This is the multiplier for the "penalty" given
                // to the players if the monster enters this state. You can put the damage
                // field on any state and the monster will "damage" the players accordingly.
        },
        "standing": {
            "msg": [
                ...
            ],
            "hurt_by": ["👊", "🦵"], // The emojis that can hurt the monster in this state.
                // These must be actual emojis.

            "default": true, // Whatever state has this field set to true will be the first
                // state that the monster will enter after its arriving state.
                // This state is completely optional; your monster does not need a default state

            "added_armor": 0.25, // an optional field. This is added to the default armor
                // during this state. This can also be negative if for instance you want
                // the monster to be particularly vulnerable during this state

            "active": true, // states that are marked as active will be the states that
                // the monster randomly cycles through

            "hittable": true // states that the monster is hittable in. States without
                // this flag can even dodge bombs.
        },
        "crouching": {
            "msg": [
                "The {name} crouches under all your punches",
                "The {name} crouches, avoiding all the punches!"
            ],
            "hurt_by": ["🦵"],
            "active": true,
            "hittable": true,
            "weight": 1.25, // an optional field. This is the chance that this state will
                // be chosen from the list of active states. Like arrival_weight,
                // 1 is normal, 2 is twice as likely, and 0.5 is half as likely

            "next_state": ["crouching", "standing"], // an optional field. If this field is present,
                // it must be a list (although the list can have only a single state in it if you wish).
                // This list will be used to randomly choose from (the weight fields are still
                // taken into account) to be the next state. This is useful for creating animation
                // sequences or "charge-up" attacks
        },
        ...
    }
}
```

Once you've created a `stats.json`, you need an image or gif for each state. Place them in the monster's `animations` folder.

The gifs currently used were made using a combination of PICO-8 and gifsicle (the pico8 cog works perfectly for this).

If you want to make similar gifs to fit the same vibe, you can either use a pixel art software like Aseprite or you can use PICO-8. Making it with PICO-8, you will need PICO-8 and gifsicle installed, then 
* alter the `jelly-sprites.p8` file in PICO-8, altering the variables in the `_init` function
* rename the gif to `a.gif`
* then run the `gifsicle` commands at the bottom of the `jelly-sprites.p8` file. Note you might need to adjust the `96x96` to be the size of your gif. My PICO-8 is set to have a gif_scale of 6, so 6 x 16 = 96.
* rename `output.gif` to the state accordingly

> Please include your source `.p8` or Aseprite file alongside the `stats.json` when making a PR file, so that people can easily edit your animation/image later on.

<!-- omit in toc -->
## Attribution
This guide is based on the **contributing-gen**. [Make your own](https://github.com/bttger/contributing-gen)!

