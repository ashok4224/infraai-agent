/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Arial', 'Helvetica', 'sans-serif'],
      },
      colors: {
        brand: {
          50:  '#E8EDF5',
          100: '#C5D2E8',
          200: '#9FB4D9',
          300: '#7996CA',
          400: '#5C80BF',
          500: '#0B3D91', // Winfo primary deep blue
          600: '#0A3780',
          700: '#082C66',
          800: '#06214D',
          900: '#041633',
        },
        accent: {
          50:  '#FFF3E0',
          100: '#FFE0B2',
          200: '#FFCC80',
          300: '#FFB74D',
          400: '#FFA726',
          500: '#F57C00', // Winfo accent orange
          600: '#EF6C00',
          700: '#E65100',
          800: '#BF360C',
          900: '#8D2700',
        },
        severity: {
          critical: '#DC2626',
          warning:  '#F59E0B',
          info:     '#3B82F6',
          low:      '#10B981',
        },
      },
    },
  },
  plugins: [],
};
