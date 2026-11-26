/** Tema Elit's Park — navy profundo + ciano, fontes Inter/Space Grotesk.
 *  O CSS compilado vai para static/css/theme.css (commitado para o Pages). */
module.exports = {
  content: [
    './templates/**/*.html',
    './*.html',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#070c1a', 900: '#0a1020', 850: '#0c1424',
          800: '#0f1a2e', 700: '#14223a',
        },
        brand: {
          50: '#effefb', 200: '#a9f0ea', 300: '#7ee7e0', 400: '#55d5d0',
          500: '#3ec9c4', 600: '#2aa8a4', 700: '#1f8582',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        disp: ['"Space Grotesk"', 'sans-serif'],
      },
      borderColor: {
        DEFAULT: 'rgba(148,163,184,.13)',
      },
      boxShadow: {
        card: '0 15px 45px rgba(0,0,0,.13)',
        toast: '0 14px 40px rgba(0,0,0,.55)',
      },
    },
  },
  plugins: [require('preline/plugin')],
};
