# Campus Grievance Desk

An anonymous grievance-submission portal for a campus: students submit a
grievance and get a private tracking ID back; anyone with that ID can check
its status; admins triage everything from a dashboard.

This is a **restyle** of an existing working Flask app — the routes,
validation, CSRF protection, rate limiting, and database logic are unchanged.
What's new is the templates (now share a common `base.html`), the CSS design
system, a small vanilla-JS layer for toasts/loading states/copy-to-clipboard,
and a couple of small additive backend touches (flash messages on admin
updates, a dashboard stats summary computed from data already being fetched).

