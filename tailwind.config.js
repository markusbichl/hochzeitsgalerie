// tailwind.config.js (CJS, works great with the standalone CLI)
module.exports = {
  content: [
    "./templates/**/*.{html,htm,jinja,jinja2}",
    "./static/**/*.{js,ts}",
    "./index.html",
    // include flowbite component sources so classes are not purged
    "./node_modules/flowbite/**/*.js",
  ],
  theme: { extend: {} },
  // Add any classes you toggle purely from JS (if any)
  safelist: [
    // example: 'hidden','block'
  ],
  plugins: [
    require('flowbite/plugin')   // enable flowbite’s Tailwind components
  ],
  darkMode: 'class',
};
