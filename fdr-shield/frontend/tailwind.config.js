export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: { display: ['Cabin', 'ui-sans-serif', 'system-ui', 'sans-serif'] },
      colors: {
        navy: { 900: '#273544' },
        primary: { 50: '#eaf3ff', 100: '#dcecff', 700: '#2563eb', 900: '#273544' },
        brand: { blue: '#3182f6', 'blue-dark': '#2563eb', 'blue-wash': '#eaf3ff', success: '#22a06b', warning: '#d79a18', ink: '#273544', line: '#d8e1ea', surface: '#f5f8fc' },
        trust: { green: '#15803d', yellow: '#b45309', red: '#b91c1c' },
      },
    },
  },
  plugins: [],
};
