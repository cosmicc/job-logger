FROM nginx:1.27-alpine

# Remove the stock site so a failed template render cannot silently serve the
# default nginx 404 page instead of proxying to the FastAPI application.
RUN rm -f /etc/nginx/conf.d/default.conf

# Self-contained error documents keep proxy-generated failures visually aligned
# with the app even when the Python service is not reachable.
COPY errors/ /usr/share/nginx/html/errors/

# The official nginx entrypoint renders templates from this directory into
# /etc/nginx/conf.d at container startup.
COPY templates/default.conf.template /etc/nginx/templates/default.conf.template
