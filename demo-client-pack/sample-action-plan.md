# Demonstration action plan - synthetic evidence only

This example uses the two synthetic pages in the accompanying evidence.json. It demonstrates how
the project skill turns observations into client decisions. No real traffic, rankings or results
were measured.

## Recommended decisions

1. **Repair malformed JSON-LD on /services.html (SEO-002).** The supplied page contains a JSON syntax
   error. Owner: developer. Acceptance: the JSON parses, then the selected schema validator confirms
   relevant properties. The current evidence proves a parse error, not a ranking loss.
2. **Review the missing description on /services.html (SEO-001).** Owner: content/SEO. Write an accurate
   summary aligned with the service once the business offering is confirmed. Acceptance: a description
   is present and correctly describes the page. Do not promise a particular Google snippet.
3. **Review the short service text against real customer intent.** This is a hypothesis from limited
   text, not a confirmed quality defect. Obtain the business goal and customer questions before
   expanding it. No fixed word target is justified by this sample.

## What not to infer

- The GPTBot block is a training-control choice; no removal is recommended for the search score.
- A low internal model score does not establish low rankings or missing AI citations.
- No keyword source, GSC export, conversion data or local listing was supplied. Those results remain
  Not verified. No keyword volumes or ranking claims are added to the map.

## Sequencing

Days 1-30: confirm intended page behavior, repair JSON-LD, review the description and recrawl.
Days 31-60: collect business priorities and query evidence, then prepare an intent-based content brief.
Days 61-90: compare comparable search-performance and conversion periods if data becomes available.
Track completed changes separately from traffic outcomes; there is no guaranteed ranking deadline.
