const express = require('express');
const router = express.Router();

router.get('/', (req, res) => {
    res.json({ strategies: ['Preparation', 'Active Listening', 'Assertive Communication'] });
});

module.exports = router;