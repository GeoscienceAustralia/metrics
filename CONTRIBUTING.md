# Contributing guide

## Code Style
### JavaScript and JSON
This repo uses [ESLint](http://eslint.org/) to enforce our style guide for the JavaScript and JSON files.

To configure ESLint:
1. Install an ESLint extension for your preffered code editor
2. Install ESLint globally using `npm install -g eslint`
3. Install ESLint JSON plugin `npm install -g eslint-plugin-json`
4. Run the install-hooks script `bin/create-hooks-symlinks` to create a pre-commit ESLint check

The ESLint extension should pick up the .ESLint.yml file in this repo and display an error or warning if any style rules are broken.
ESLint can also be run from the console using `eslint **/* --ext .json` this will run ESLint on all files that have not been ignored using the .ESLintignore file.
`--ext .json` is used to tell ESLint that we want to inspect .json files as well as .js files.

The style rules can be ignored using `//eslint-disable-line rule-name`
This should only be used in circumstances when the intention of the rule does not apply.