import React, { useEffect, useState } from 'react';
import { Bar } from 'react-chartjs-2';
import { BrowserRouter as Router, Route, Switch } from 'react-router-dom';
import Login from './Login';
import Dashboard from './Dashboard';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  return (
    <Router>
      <div className="App">
        <h1>AI-powered Productivity Analytics Dashboard</h1>
        <Switch>
          <Route path="/login">
            <Login setIsAuthenticated={setIsAuthenticated} />
          </Route>
          <Route path="/dashboard">
            {isAuthenticated ? <Dashboard /> : <Redirect to="/login" />}
          </Route>
          <Redirect from="/" to="/login" />
        </Switch>
      </div>
    </Router>
  );
}

export default App;