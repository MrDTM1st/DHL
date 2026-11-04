import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './theme.css';
import * as theme from './lib/theme.js';

theme.apply();
theme.follow();
createRoot(document.getElementById('root')).render(<App />);
