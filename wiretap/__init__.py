"""Demo wiretap: record every byte the app sends to the document servers, then search it for the
asker's words. It sits between the app and the servers, so the proof does not rely on the servers'
own logs. See wiretap/proxy.py and wiretap/search.py."""
