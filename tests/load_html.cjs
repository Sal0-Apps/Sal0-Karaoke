const fs = require('fs');
module.exports = () => fs.readFileSync('app/templates/index.html','utf8').replace('{% include \"queue_cache_panel.html\" %}',fs.readFileSync('app/templates/queue_cache_panel.html','utf8'));
