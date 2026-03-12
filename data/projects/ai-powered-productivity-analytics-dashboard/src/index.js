const express = require('express');
const app = express();
const PORT = process.env.PORT || 5000;

app.get('/', (req, res) => {
    res.send('Welcome to the AI-powered Productivity Analytics Dashboard!');
});

app.listen(PORT, () => {
    console.log(`Server is running on http://localhost:${PORT}`);
});