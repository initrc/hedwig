"""Turn a whole day's parsed newsletter emails into one finished digest.

This package holds the steps that do that, run one after another: split each
email into its separate stories, group the stories by topic, write up each topic,
pull out action items, pick a picture, and save the result. They run together
over a day's emails in a single scheduled pass — not one email at a time as each
arrives — because grouping by topic only makes sense once you can see all of the
day's stories side by side. That is why the steps here work on lists of things,
not single messages.

Segmentation (`segment.py`) is the first step: it turns one email into its
stories so the grouping step has something finer than whole emails to work with.
Clustering (`cluster.py`) is the second: it groups the day's stories into
labelled topics, so the steps after it write up one topic at a time.
"""
